#!/usr/bin/env python3
"""Physical PCAP -> the original 23 predictors, with audited external labels.

TShark writes to disk. Pandas processes bounded blocks ending on a 2 s boundary.
The original aggregation and clean-table functions are vendored without changes.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import math
from pathlib import Path
import sqlite3
import subprocess
import sys

import numpy as np
import pandas as pd

from vendor import coap_features as original
from vendor.clean_table import FEATURES, build_clean

ROOT = Path(__file__).resolve().parent
WINDOWS = (0.5, 1.0, 2.0)
LABELS = {"benign": "benign", "block2_amplification": "coap_block2_amplification_flood",
          "request_flood": "coap_request_flood"}
COMPLETE = json.loads((ROOT / "complete_columns.json").read_text())
EXCLUDED = ["meta_session", "meta_win_idx", "meta_endpoint_a", "meta_endpoint_b",
            "meta_window_seconds", "meta_n_frames", "exclusion_reason"]


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def resolve(base, value):
    return (base / value).resolve()


def packet_blocks(tsv, chunksize=20000):
    """Never split a window for any of 0.5/1/2 s; retain the last 2 s bucket."""
    tail = None
    previous_time = -math.inf
    with pd.read_csv(tsv, sep="\t", dtype=str, keep_default_na=False,
                     na_filter=False, chunksize=chunksize) as reader:
        for frame in reader:
            for name in original.NUMERIC_FIELDS:
                frame[name] = pd.to_numeric(frame[name], errors="coerce")
            required = ["frame.number", "frame.time_relative", "frame.time_epoch", "frame.len", "coap.code", "coap.type"]
            if frame[required].isna().any().any() or frame["ip.src"].eq("").any() or frame["ip.dst"].eq("").any():
                raise ValueError("Incomplete decoded CoAP fields; inspect packet_extract before labelling.")
            times = frame["frame.time_relative"].to_numpy()
            if len(times) and (times[0] < previous_time or np.any(np.diff(times) < 0)):
                raise ValueError("Capture timestamps are not monotonic; no silent reordering is performed.")
            if not len(frame):
                continue
            previous_time = times[-1]
            frame = pd.concat([tail, frame], ignore_index=True) if tail is not None else frame
            bucket = np.floor(frame["frame.time_relative"] / 2 + original.EPS)
            mask = bucket < bucket.iloc[-1]
            if mask.any():
                yield frame.loc[mask].copy()
            tail = frame.loc[~mask].copy()
    if tail is not None and len(tail):
        yield tail


class GroundTruth:
    def __init__(self, session, base, work):
        self.session = session
        self.server = session["server_ip"]
        self.benign = set(session["benign_ips"])
        self.actor_ip = None
        self.phases = {}
        self.db = None
        self.input_files = []
        self.packet_counts = Counter()
        self.observed_benign = set()
        self.offset = self.uncertainty = 0.0
        if not self.benign or self.server in self.benign:
            raise ValueError("Specify the observed legitimate clients separately from the server.")
        for address in [self.server, *self.benign]:
            ipaddress.IPv4Address(address)
        actor = session.get("actor")
        if not actor:
            if session.get("traffic_declaration") != "benign_only":
                raise ValueError("A capture without actor logs requires an explicit benign_only declaration.")
            return
        self.actor_ip = actor["ip"]
        ipaddress.IPv4Address(self.actor_ip)
        if self.actor_ip in self.benign or self.actor_ip == self.server:
            raise ValueError("Actor, server and physical clients must have distinct IP addresses.")
        clock_file = resolve(base, actor["clock_file"])
        clock = read_json(clock_file)
        self.offset = float(clock["actor_minus_capture_seconds"])
        self.uncertainty = float(clock["uncertainty_seconds"])
        if not math.isfinite(self.offset) or not 0 <= self.uncertainty < 1:
            raise ValueError("A finite clock offset and uncertainty below one second are required.")
        if not clock.get("method") or not clock.get("evidence"):
            raise ValueError("Clock correction requires a documented method and measured evidence.")
        directory = resolve(base, actor["directory"])
        self.input_files = [clock_file, *[directory / name for name in
                           ["manifest.json", "summary.json", "plan.json", "events.jsonl", "traffic.jsonl", "sha256.json"]]]
        inventory = read_json(directory / "sha256.json")
        for name in ["manifest.json", "summary.json", "plan.json", "events.jsonl", "traffic.jsonl"]:
            if inventory.get(name) != sha256(directory / name):
                raise ValueError(f"Actor hash mismatch: {name}")
        manifest = read_json(directory / "manifest.json")
        summary = read_json(directory / "summary.json")
        if manifest["server"] != self.server or summary["status"] != "completed" or summary["log_dropped_records"]:
            raise ValueError("Actor destination/status/log integrity does not support a complete labelled session.")
        if "host_clock_changed" in summary.get("quality_flags", []):
            raise ValueError("Actor clock changed during the session; reconcile clocks before extraction.")
        self.timeout = read_json(directory / "plan.json")["response_timeout_ms"] / 1000
        ports = {lane["lane"]: lane["local"]["port"] for lane in summary["lanes"]}
        for phase in summary["phases"]:
            if phase["label"] not in LABELS:
                continue
            start = max(phase["scheduler_start_epoch"], phase["scheduled_start_epoch"]) - self.offset
            end = min(phase["scheduler_end_epoch"], phase["scheduled_end_epoch"]) - self.offset
            self.phases[phase["phase_id"]] = {**phase, "capture_start": start, "capture_end": end}
        self.db = sqlite3.connect(work)
        self.db.execute("CREATE TABLE tx (id TEXT PRIMARY KEY, port INTEGER, mid INTEGER, token TEXT, type INTEGER, phase TEXT, epoch REAL, accepted INTEGER DEFAULT 0)")
        with (directory / "traffic.jsonl").open(encoding="utf-8") as handle:
            for line in handle:
                item = json.loads(line)
                if item["kind"] == "tx":
                    self.db.execute("INSERT INTO tx(id,port,mid,token,type,phase,epoch) VALUES(?,?,?,?,?,?,?)",
                                    (item["request_id"], ports[item["lane"]], item["mid"], item["token"].lower(),
                                     0 if item["message_type"] == "CON" else 1, item["phase_id"], item["epoch"] - self.offset))
                elif item["kind"] == "send_result":
                    self.db.execute("UPDATE tx SET accepted=? WHERE id=?", (int(item["accepted_by_udp"]), item["request_id"]))
        for columns in ["port,mid,token", "port,token,type", "port,mid"]:
            self.db.execute(f"CREATE INDEX idx_{columns.replace(',', '_')} ON tx({columns})")
        self.db.commit()

    def annotate(self, raw):
        tags = []
        for row in raw.to_dict("records"):
            a, b = row["ip.src"], row["ip.dst"]
            if self.server not in (a, b):
                tag = "unknown_pair"
            else:
                peer = b if a == self.server else a
                if peer in self.benign:
                    tag = "physical_benign"
                    self.observed_benign.add(peer)
                elif peer != self.actor_ip:
                    tag = "unknown_participant"
                else:
                    port = int(row["udp.dstport"] if a == self.server else row["udp.srcport"])
                    token = row["coap.token"].replace(":", "").lower()
                    mid, kind = int(row["coap.mid"]), int(row["coap.type"])
                    if a == self.actor_ip or kind == 2:
                        where, args = "port=? AND mid=? AND token=?", (port, mid, token)
                    elif kind == 3:
                        where, args = "port=? AND mid=?", (port, mid)
                    else:
                        where, args = "port=? AND token=? AND type=1", (port, token)
                    candidates = self.db.execute(f"SELECT phase,epoch FROM tx WHERE accepted=1 AND {where}", args).fetchall()
                    t = row["frame.time_epoch"]
                    candidates = [(phase, epoch) for phase, epoch in candidates
                                  if -self.uncertainty <= t - epoch <= self.timeout + self.uncertainty]
                    tag = candidates[0][0] if len(candidates) == 1 else "unmatched_actor_packet"
            self.packet_counts[tag] += 1
            tags.append(tag)
        raw["_truth"] = tags
        return raw

    def label(self, raw, windows, width, capture_end):
        pairs = [tuple(sorted((a, b))) for a, b in zip(raw["ip.src"], raw["ip.dst"])]
        keys = zip(np.floor(raw["frame.time_relative"] / width + original.EPS).astype(int), pairs, raw["_truth"])
        tags = {}
        for index, pair, tag in keys:
            tags.setdefault((index, *pair), set()).add(tag)
        kept, excluded = [], []
        observation_start = self.session.get("observation_start_epoch", -math.inf)
        observation_end = min(capture_end, self.session.get("observation_end_epoch", math.inf))
        for row in windows.to_dict("records"):
            key = (row["meta_win_idx"], row["meta_endpoint_a"], row["meta_endpoint_b"])
            assigned = tags[key]
            start, end = row["_win_epoch_start"], row["_win_epoch_end"]
            reason, phase_id, label, strategy, source = None, "none", "benign", "none", "documented_physical_client"
            if start < observation_start - 1e-6 or end > observation_end + 1e-6:
                reason = "outside_complete_observation_interval"
            elif assigned == {"physical_benign"}:
                pass
            elif len(assigned) != 1:
                reason = "mixed_or_unmatched_packet_origins"
            else:
                phase_id = next(iter(assigned))
                phase = self.phases.get(phase_id)
                if phase is None:
                    reason = "preflight_guard_or_unknown_packet_origin"
                elif start < phase["capture_start"] + self.uncertainty - 1e-6 or end > phase["capture_end"] - self.uncertainty + 1e-6:
                    reason = "phase_boundary_or_clock_uncertainty"
                else:
                    label, strategy = LABELS[phase["label"]], phase["kind"]
                    source = "external_actor_log_and_packet_correlation"
            row["meta_dataset_source"] = self.session.get("dataset_source", "physical_coap_v1")
            if reason:
                excluded.append({**row, "exclusion_reason": reason})
                continue
            row.update(label_binary=int(label != "benign"), label_attack=label, label_episode=phase_id,
                       label_overlap_fraction=1.0 if label != "benign" else 0.0,
                       label_confidence="high", label_source=source, label_attack_strategy=strategy)
            kept.append(row)
        return pd.DataFrame(kept, columns=COMPLETE), pd.DataFrame(excluded, columns=EXCLUDED)

    def close(self):
        if self.db is not None:
            self.db.close()


def export_packets(pcap, destination, port=5683):
    command = ["tshark", "-n", "-r", str(pcap), "-d", f"udp.port=={port},coap", "-Y", "coap", "-T", "fields",
               "-E", "header=y", "-E", "separator=/t", "-E", "quote=d", "-E", "occurrence=f"]
    for field in original.FIELDS:
        command.extend(["-e", field])
    with destination.open("w", encoding="utf-8", newline="") as out, destination.with_suffix(".stderr.txt").open("w", encoding="utf-8") as err:
        subprocess.run(command, stdout=out, stderr=err, check=True)
    return command


def append_csv(frame, path):
    frame.to_csv(path, mode="a", header=not path.exists(), index=False, float_format="%.9g", encoding="utf-8")


def build(manifest_path, output, chunksize=20000):
    manifest_path, output = Path(manifest_path).resolve(), Path(output).resolve()
    manifest = read_json(manifest_path)
    sessions = manifest["sessions"]
    names = [s["session"] for s in sessions]
    if not sessions or len(set(names)) != len(names) or any(not name or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for c in name) or name in (".", "..") for name in names):
        raise ValueError("Session identifiers must be nonempty, unique and safe filenames.")
    if chunksize < 1:
        raise ValueError("chunksize must be positive")
    output.mkdir(parents=True, exist_ok=False)
    extraction = output / "packet_extract"
    extraction.mkdir()
    reports = []
    for session in sessions:
        name = session["session"]
        pcap = resolve(manifest_path.parent, session["pcap"])
        truth = GroundTruth(session, manifest_path.parent, extraction / f"{name}.sqlite")
        tsv = extraction / f"{name}.tsv"
        report = {"session": name, "pcap": str(pcap), "pcap_sha256": sha256(pcap), "coap_packets": 0,
                  "declared_benign_ips": session["benign_ips"], "actor_ip": truth.actor_ip,
                  "inputs": {str(p): sha256(p) for p in truth.input_files}, "windows": {}}
        try:
            report["tshark_command"] = export_packets(pcap, tsv, session.get("server_port", 5683))
            # One-block lookahead identifies the true final observed timestamp.
            blocks = iter(packet_blocks(tsv, chunksize))
            current = next(blocks, None)
            if current is None:
                raise ValueError(f"No decoded CoAP packets in {pcap}")
            while current is not None:
                following = next(blocks, None)
                current = truth.annotate(current)
                report["coap_packets"] += len(current)
                end = current["frame.time_epoch"].max() if following is None else math.inf
                for width in WINDOWS:
                    suffix = str(width).replace(".", "_") + "s"
                    directory = output / suffix
                    directory.mkdir(exist_ok=True)
                    windows = original.aggregate(current, name, width)
                    main, excluded = truth.label(current, windows, width, end)
                    append_csv(main, directory / "dataset_complete_tracking.csv")
                    append_csv(build_clean(main), directory / "dataset_clean_multiclass.csv")
                    append_csv(excluded, directory / "excluded_windows.csv")
                    stats = report["windows"].setdefault(suffix, {"kept": 0, "excluded": 0, "classes": Counter(), "reasons": Counter()})
                    stats["kept"] += len(main)
                    stats["excluded"] += len(excluded)
                    stats["classes"].update(main["label_attack"].value_counts().to_dict())
                    stats["reasons"].update(excluded["exclusion_reason"].value_counts().to_dict())
                current = following
        finally:
            truth.close()
        report["packet_ground_truth_counts"] = dict(truth.packet_counts)
        report["observed_benign_clients"] = sorted(truth.observed_benign)
        reports.append(report)
        print(f"{name}: {report['coap_packets']} packets, {report['windows']['1_0s']['kept']} retained 1 s windows", flush=True)
    result = {"schema": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
              "source_manifest": str(manifest_path), "source_manifest_sha256": sha256(manifest_path),
              "tshark": original.tshark_version(), "python": sys.version, "pandas": pd.__version__, "numpy": np.__version__,
              "window_seconds": list(WINDOWS), "predictors": FEATURES, "grouping": "unordered IPv4 pair; capture-relative aligned nonoverlapping windows",
              "final_window_policy": "exclude windows ending after the final observed CoAP frame",
              "upstream": read_json(ROOT / "vendor/UPSTREAM.json"), "extractor_sha256": sha256(__file__), "sessions": reports,
              "outputs": {str(p.relative_to(output)): sha256(p) for p in output.glob("*/*.csv")}}
    (output / "build_manifest.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--chunksize", type=int, default=20000)
    args = parser.parse_args()
    build(args.manifest, args.output, args.chunksize)


if __name__ == "__main__":
    main()
