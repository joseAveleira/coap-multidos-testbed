#!/usr/bin/env python3
"""Describe a completed physical acquisition without training/evaluating models."""
import argparse
from collections import Counter, defaultdict
import csv
import json
import tempfile
from pathlib import Path, PureWindowsPath

import numpy as np
import pandas as pd

from extract import GroundTruth, packet_blocks, read_json, sha256


def audit(capture, exported):
    execution = read_json(capture / "execution.json")
    if execution["status"] != "captured_pending_extraction":
        raise ValueError("Only a completed capture can be audited as a dataset session")
    build = read_json(exported / "build_manifest.json")
    source_manifest = Path(build["source_manifest"])
    # Published build records retain the original acquisition host path. Locate
    # the same immutable manifest beside the PCAP after moving the repository.
    if not source_manifest.is_file():
        source_manifest = capture / PureWindowsPath(build["source_manifest"]).name
    if sha256(source_manifest) != build["source_manifest_sha256"]:
        raise ValueError("Source manifest differs from the verified export")
    manifest = read_json(source_manifest)
    if len(manifest["sessions"]) != 1:
        raise ValueError("Audit one capture session at a time")
    session = manifest["sessions"][0]
    report = next(s for s in build["sessions"] if s["session"] == session["session"])
    assert report["pcap_sha256"] == sha256(capture / session["pcap"])
    for name, digest in build["outputs"].items():
        if sha256(exported / name) != digest:
            raise ValueError(f"Export hash mismatch: {name}")
    actor = capture / session["actor"]["directory"]
    summary, plan = read_json(actor / "summary.json"), read_json(actor / "plan.json")
    clock = read_json(capture / session["actor"]["clock_file"])
    delays = defaultdict(list)
    with (actor / "traffic.jsonl").open(encoding="utf-8") as f:
        for line in f:
            item = json.loads(line)
            if item["kind"] == "rx" and item["valid"]:
                delays[item["phase_id"]].append(item["elapsed_ms"])
    with tempfile.TemporaryDirectory(prefix=".coap-audit-", dir=exported.resolve()) as temporary:
        assert Path(temporary).resolve().parent == exported.resolve()
        database = Path(temporary) / "correlations.sqlite"
        truth = GroundTruth(session, capture, database)
        packets, phases = defaultdict(Counter), defaultdict(Counter)
        first, last = float("inf"), float("-inf")
        try:
            for raw in packet_blocks(exported / "packet_extract" / (session["session"] + ".tsv")):
                tagged = truth.annotate(raw)
                first = min(first, tagged["frame.time_epoch"].min())
                last = max(last, tagged["frame.time_epoch"].max())
                for row in tagged.to_dict("records"):
                    peer = row["ip.src"] if row["ip.dst"] == session["server_ip"] else row["ip.dst"]
                    kind = "requests" if row["coap.code"] == 1 else "responses" if row["coap.code"] >= 64 else "other"
                    packets[peer][kind] += 1
                    phases[row["_truth"]][kind] += 1
        finally:
            truth.close()
    planned = {p["id"]: p for p in plan["phases"]}
    rows = []
    for phase in summary["phases"]:
        if phase["kind"] == "guard":
            continue
        identifier = phase["phase_id"]
        values = delays[identifier]
        rows.append({"phase_id": identifier, "kind": phase["kind"], "label": phase["label"],
            "message_type": planned[identifier]["message_type"],
            "scheduled_duration_s": planned[identifier]["duration_s"],
            "capture_start_epoch": phase["scheduler_start_epoch"] - clock["actor_minus_capture_seconds"],
            "capture_end_epoch": phase["scheduler_end_epoch"] - clock["actor_minus_capture_seconds"],
            **{k: phase[k] for k in ["target_rate_rps", "achieved_send_rate_rps", "accepted_by_udp", "valid_responses",
                 "timeouts", "scheduler_skipped_slots", "capacity_skipped_slots"]},
            "requests_seen_at_server": phases[identifier]["requests"],
            "responses_seen_at_server": phases[identifier]["responses"],
            "valid_response_elapsed_ms_median": float(np.median(values)) if values else None,
            "valid_response_elapsed_ms_p95": float(np.percentile(values, 95)) if values else None})
    with (exported / "phase_summary.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    server = read_json(capture / "server" / session["session"] / "summary.json")
    audit_result = {"session": session["session"], "status": "completed_acquisition_audited",
        "capture_manifest_sha256": sha256(source_manifest),
        "build_manifest_sha256": sha256(exported / "build_manifest.json"),
        "pcap_sha256": report["pcap_sha256"], "timestamp_ordering": session.get("timestamp_ordering"),
        "observed_clients": execution["devices_observed_in_campaign"],
        "actor": session["actor"]["ip"], "actor_status": summary["status"],
        "actor_dropped_records": summary["log_dropped_records"],
        "actor_clock_disagreement_ms": summary["clock_max_wall_disagreement_ms"],
        "clock_correction": clock, "first_packet_epoch": first, "last_packet_epoch": last,
        "observed_packet_span_seconds": last - first, "packets_by_peer": packets,
        "packets_by_correlated_phase": phases, "windows": report["windows"],
        "executed_attack_episodes": dict(Counter(row["label"] for row in rows if row["label"] != "benign")),
        "phase_summary": rows, "server_summary": server,
        "capture_drops": "consult tshark.stderr.txt; not assumed zero when unavailable",
        "interpretation": "Scheduled workload classes; elapsed response times describe acquisition and do not establish a DoS effect or classifier performance."}
    (exported / "acquisition_audit.json").write_text(json.dumps(audit_result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: audit_result[k] for k in ["session", "status", "actor_status", "actor_dropped_records", "packets_by_peer", "executed_attack_episodes", "windows"]}, indent=2))
    return audit_result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--export", type=Path, required=True)
    args = parser.parse_args()
    audit(args.capture.resolve(), args.export.resolve())
