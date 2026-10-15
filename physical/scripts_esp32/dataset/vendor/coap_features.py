#!/usr/bin/env python3
"""CoAP packet extraction, window aggregation and labelling helpers."""

from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd


EPS = 1e-12

FIELDS = [
    "frame.number",
    "frame.time_relative",
    "frame.time_epoch",
    "frame.len",
    "ip.src",
    "ip.dst",
    "ip.ttl",
    "udp.srcport",
    "udp.dstport",
    "coap.type",
    "coap.code",
    "coap.mid",
    "coap.token",
    "coap.opt.observe",
    "coap.opt.uri_path",
    "coap.payload_length",
    "coap.opt.block_number",
    "coap.opt.block_mflag",
    "coap.opt.block_size",
    "coap.block_length",
]

NUMERIC_FIELDS = [
    "frame.number",
    "frame.time_relative",
    "frame.time_epoch",
    "frame.len",
    "ip.ttl",
    "udp.srcport",
    "udp.dstport",
    "coap.type",
    "coap.code",
    "coap.mid",
    "coap.payload_length",
    "coap.opt.block_number",
    "coap.opt.block_mflag",
    "coap.opt.block_size",
    "coap.block_length",
]

def tshark_version() -> str:
    result = subprocess.run(
        ["tshark", "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return result.stdout.splitlines()[0]


def extract_packets(pcap: Path) -> pd.DataFrame:
    command = [
        "tshark",
        "-n",
        "-r",
        str(pcap),
        "-Y",
        "coap",
        "-T",
        "fields",
        "-E",
        "header=y",
        "-E",
        "separator=/t",
        "-E",
        "quote=d",
        "-E",
        "occurrence=f",
    ]
    for field in FIELDS:
        command.extend(("-e", field))
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode:
        raise RuntimeError(f"TShark falló para {pcap}:\n{result.stderr}")
    frame = pd.read_csv(
        io.StringIO(result.stdout),
        sep="\t",
        dtype=str,
        keep_default_na=False,
        na_filter=False,
    )
    for field in NUMERIC_FIELDS:
        frame[field] = pd.to_numeric(frame[field], errors="coerce")
    frame = frame.dropna(
        subset=["frame.number", "frame.time_relative", "frame.time_epoch", "frame.len", "coap.code"]
    ).copy()
    frame = frame.loc[frame["ip.src"].ne("") & frame["ip.dst"].ne("")]
    return frame.sort_values("frame.time_epoch", kind="stable").reset_index(drop=True)


def entropy(series: pd.Series) -> float:
    counts = series.value_counts().to_numpy(dtype=float)
    if counts.sum() == 0:
        return 0.0
    probability = counts / counts.sum()
    return float(-(probability * np.log2(probability)).sum())


def iat_values(series: pd.Series, window_seconds: float) -> pd.Series:
    delta = np.diff(np.sort(series.to_numpy(dtype=float)))
    if len(delta) == 0:
        return pd.Series({"core_mean_iat": window_seconds, "core_std_iat": 0.0})
    return pd.Series(
        {"core_mean_iat": float(delta.mean()), "core_std_iat": float(delta.std(ddof=0))}
    )


def block_request_stats(group: pd.DataFrame) -> pd.Series:
    requests = group.loc[group["is_block_request"]].sort_values("frame.time_epoch", kind="stable")
    count = len(requests)
    if count == 0:
        return pd.Series(
            {
                "coap_block2_mean_number": 0.0,
                "coap_block2_unique_numbers": 0,
                "coap_block2_sequential_req_frac": 0.0,
                "coap_block2_repeated_req_frac": 0.0,
                "coap_block2_req_unique_token_frac": 0.0,
            }
        )
    numbers = requests["coap.opt.block_number"].astype(int).to_numpy()
    unique_numbers = int(pd.Series(numbers).nunique())
    if count > 1:
        difference = np.diff(numbers)
        sequential = float(np.mean((difference == 1) | ((numbers[:-1] == 31) & (numbers[1:] == 0))))
    else:
        sequential = 0.0
    unique_tokens = requests["coap.token"].replace("", np.nan).nunique(dropna=True)
    return pd.Series(
        {
            "coap_block2_mean_number": float(numbers.mean()),
            "coap_block2_unique_numbers": unique_numbers,
            "coap_block2_sequential_req_frac": sequential,
            "coap_block2_repeated_req_frac": float(1.0 - unique_numbers / count),
            "coap_block2_req_unique_token_frac": float(unique_tokens / count),
        }
    )


def aggregate(raw: pd.DataFrame, session_id: str, window_seconds: float) -> pd.DataFrame:
    frame = raw.copy()
    left_first = frame["ip.src"].le(frame["ip.dst"])
    frame["meta_endpoint_a"] = np.where(left_first, frame["ip.src"], frame["ip.dst"])
    frame["meta_endpoint_b"] = np.where(left_first, frame["ip.dst"], frame["ip.src"])
    frame["meta_win_idx"] = np.floor(frame["frame.time_relative"] / window_seconds + EPS).astype(int)

    code = frame["coap.code"]
    kind = frame["coap.type"]
    frame["is_request"] = code.between(1, 31)
    frame["is_method"] = code.between(1, 7)
    frame["is_response"] = code.ge(64)
    frame["is_success_response"] = code.between(64, 95)
    frame["is_error_response"] = code.ge(128)
    frame["is_empty"] = code.eq(0)
    frame["is_con"] = kind.eq(0)
    frame["is_non"] = kind.eq(1)
    frame["is_ack"] = kind.eq(2)
    frame["is_rst"] = kind.eq(3)
    frame["is_empty_ack"] = frame["is_empty"] & frame["is_ack"]
    frame["is_observe"] = frame["coap.opt.observe"].ne("")
    frame["is_notification"] = frame["is_response"] & frame["is_observe"]
    frame["is_block"] = frame["coap.opt.block_number"].notna()
    frame["is_block_request"] = frame["is_method"] & frame["is_block"]
    frame["is_block_response"] = frame["is_response"] & frame["is_block"]
    frame["is_block_more_response"] = (
        frame["is_block_response"] & frame["coap.opt.block_mflag"].fillna(0).eq(1)
    )
    frame["payload_len"] = np.where(
        frame["coap.block_length"].notna(),
        frame["coap.block_length"].fillna(0),
        frame["coap.payload_length"].fillna(0),
    )
    frame["block_payload_len"] = np.where(
        frame["is_block_response"], frame["coap.block_length"].fillna(0), 0
    )
    frame["block_request_wire_bytes"] = np.where(frame["is_block_request"], frame["frame.len"], 0)
    frame["block_response_wire_bytes"] = np.where(frame["is_block_response"], frame["frame.len"], 0)

    keys = ["meta_win_idx", "meta_endpoint_a", "meta_endpoint_b"]
    grouped = frame.groupby(keys, sort=True, observed=True)
    sums = [
        "is_request",
        "is_response",
        "is_success_response",
        "is_error_response",
        "is_empty",
        "is_con",
        "is_non",
        "is_ack",
        "is_rst",
        "is_empty_ack",
        "is_observe",
        "is_notification",
        "is_block",
        "is_block_request",
        "is_block_response",
        "is_block_more_response",
        "block_payload_len",
        "block_request_wire_bytes",
        "block_response_wire_bytes",
    ]
    summary = grouped.agg(
        meta_n_frames=("frame.number", "size"),
        _bytes=("frame.len", "sum"),
        core_mean_len=("frame.len", "mean"),
        core_std_len=("frame.len", lambda values: float(values.std(ddof=0))),
        _first_time=("frame.time_relative", "min"),
        _last_time=("frame.time_relative", "max"),
        _payload_bytes=("payload_len", "sum"),
        coap_mean_payload_len=("payload_len", "mean"),
    )
    summary = summary.join(grouped[sums].sum())
    summary = summary.join(
        grouped["frame.time_relative"].apply(lambda values: iat_values(values, window_seconds)).unstack()
    )
    summary = summary.join(grouped.apply(block_request_stats, include_groups=False))

    requests = frame.loc[frame["is_method"]]
    request_groups = requests.groupby(keys, sort=True, observed=True)
    summary["coap_method_entropy"] = (
        request_groups["coap.code"].apply(entropy).reindex(summary.index).fillna(0.0)
    )
    summary["coap_distinct_methods"] = (
        request_groups["coap.code"].nunique().reindex(summary.index).fillna(0).astype(int)
    )
    request_count = request_groups.size().reindex(summary.index).fillna(0)
    unique_mid = request_groups["coap.mid"].nunique().reindex(summary.index).fillna(0)
    summary["coap_req_mid_reuse_frac"] = np.where(
        request_count.gt(0), 1.0 - unique_mid / request_count, 0.0
    )

    summary = summary.reset_index()
    count = summary["meta_n_frames"].astype(float)
    request = summary["is_request"].astype(float)
    response = summary["is_response"].astype(float)
    req_resp = request + response
    block_response = summary["is_block_response"].astype(float)

    result = summary[["meta_win_idx", "meta_endpoint_a", "meta_endpoint_b", "meta_n_frames"]].copy()
    result.insert(0, "meta_capture", session_id)
    result.insert(0, "meta_session", session_id)
    result.insert(0, "meta_dataset_source", "generated_coap_block2_loopback_v6")
    result["meta_win_start"] = result["meta_win_idx"] * window_seconds
    result["meta_win_end"] = result["meta_win_start"] + window_seconds
    result["meta_window_seconds"] = window_seconds
    result["meta_time_block_60s"] = np.floor(result["meta_win_start"] / 60).astype(int)
    result["core_pkts_per_s"] = count / window_seconds
    result["core_bytes_per_s"] = summary["_bytes"] / window_seconds
    result["core_mean_len"] = summary["core_mean_len"]
    result["core_std_len"] = summary["core_std_len"]
    result["core_mean_iat"] = summary["core_mean_iat"]
    result["core_std_iat"] = summary["core_std_iat"]
    result["core_active_span_frac"] = (
        (summary["_last_time"] - summary["_first_time"]) / window_seconds
    ).clip(0, 1)

    for source, target in [
        ("is_request", "coap_req_per_s"),
        ("is_response", "coap_resp_per_s"),
        ("is_empty", "coap_empty_per_s"),
        ("is_con", "coap_con_per_s"),
        ("is_non", "coap_non_per_s"),
        ("is_ack", "coap_ack_per_s"),
        ("is_rst", "coap_rst_per_s"),
        ("is_observe", "coap_observe_per_s"),
        ("is_notification", "coap_notification_per_s"),
    ]:
        result[target] = summary[source] / window_seconds
    result["coap_request_frac"] = request / count
    result["coap_response_frac"] = response / count
    result["coap_empty_ack_frac"] = summary["is_empty_ack"] / count
    result["coap_con_frac"] = summary["is_con"] / count
    result["coap_ack_frac"] = summary["is_ack"] / count
    result["coap_observe_frac"] = summary["is_observe"] / count
    result["coap_notification_frac"] = summary["is_notification"] / count
    result["coap_success_resp_frac"] = np.where(
        response.gt(0), summary["is_success_response"] / response, 0.0
    )
    result["coap_error_resp_frac"] = np.where(
        response.gt(0), summary["is_error_response"] / response, 0.0
    )
    result["coap_resp_balance"] = np.where(req_resp.gt(0), response / req_resp, 0.0)
    result["coap_log_resp_req"] = np.log1p(response) - np.log1p(request)
    result["coap_payload_bytes_per_s"] = summary["_payload_bytes"] / window_seconds
    result["coap_mean_payload_len"] = summary["coap_mean_payload_len"]
    result["coap_method_entropy"] = summary["coap_method_entropy"]
    result["coap_distinct_methods"] = summary["coap_distinct_methods"]
    result["coap_req_mid_reuse_frac"] = summary["coap_req_mid_reuse_frac"].clip(0, 1)

    result["coap_block2_per_s"] = summary["is_block"] / window_seconds
    result["coap_block2_req_per_s"] = summary["is_block_request"] / window_seconds
    result["coap_block2_resp_per_s"] = block_response / window_seconds
    result["coap_block2_frac"] = summary["is_block"] / count
    result["coap_block2_more_resp_frac"] = np.where(
        block_response.gt(0), summary["is_block_more_response"] / block_response, 0.0
    )
    for column in (
        "coap_block2_mean_number",
        "coap_block2_unique_numbers",
        "coap_block2_sequential_req_frac",
        "coap_block2_repeated_req_frac",
        "coap_block2_req_unique_token_frac",
    ):
        result[column] = summary[column]
    result["coap_block2_payload_bytes_per_s"] = summary["block_payload_len"] / window_seconds
    result["coap_block2_log_resp_req_bytes"] = (
        np.log1p(summary["block_response_wire_bytes"])
        - np.log1p(summary["block_request_wire_bytes"])
    )
    result["_win_epoch_start"] = raw["frame.time_epoch"].min() - raw["frame.time_relative"].min() + result["meta_win_start"]
    result["_win_epoch_end"] = result["_win_epoch_start"] + window_seconds
    return result.replace([np.inf, -np.inf], 0.0).fillna(0.0)


def load_events(path: Path) -> list[dict]:
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def label_session(frame: pd.DataFrame, events: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    result = frame.copy()
    result["_event_overlap"] = 0.0
    result["_event_episode"] = ""
    result["_event_attack_type"] = ""
    result["_event_strategy"] = ""
    for event in events:
        pair = frozenset((event["actor_ip"], event["server_ip"]))
        participants = pd.Series(
            [frozenset((a, b)) == pair for a, b in zip(result["meta_endpoint_a"], result["meta_endpoint_b"])],
            index=result.index,
        )
        overlap = (
            np.minimum(result["_win_epoch_end"], event["end_epoch"])
            - np.maximum(result["_win_epoch_start"], event["start_epoch"])
        ).clip(lower=0, upper=1)
        match = participants & overlap.gt(result["_event_overlap"])
        result.loc[match, "_event_overlap"] = overlap.loc[match]
        result.loc[match, "_event_episode"] = event["episode_id"]
        result.loc[match, "_event_attack_type"] = event["attack_type"]
        result.loc[match, "_event_strategy"] = event["strategy"]

    full = result["_event_overlap"].ge(1.0 - 1e-9)
    boundary = result["_event_overlap"].gt(0) & ~full
    excluded = result.loc[boundary].copy()
    excluded["label_episode"] = excluded["_event_episode"]
    excluded["label_overlap_fraction"] = excluded["_event_overlap"]
    excluded["label_exclusion_reason"] = "boundary_window_partial_attack_overlap"

    main = result.loc[~boundary].copy()
    attack = full.loc[main.index]
    main["label_binary"] = attack.astype(int)
    main["label_attack"] = np.where(attack, main["_event_attack_type"], "benign")
    main["label_episode"] = np.where(attack, main["_event_episode"], "none")
    main["label_overlap_fraction"] = np.where(attack, main["_event_overlap"], 0.0)
    main["label_confidence"] = "high"
    main["label_source"] = np.where(
        attack, "external_orchestrator_event", "externally_scheduled_benign_workload"
    )
    main["label_attack_strategy"] = np.where(attack, main["_event_strategy"], "none")

    helpers = [
        "_win_epoch_start",
        "_win_epoch_end",
        "_event_overlap",
        "_event_episode",
        "_event_attack_type",
        "_event_strategy",
    ]
    main = main.drop(columns=helpers)
    excluded = excluded.drop(columns=helpers)
    meta = [column for column in main if column.startswith("meta_")]
    features = [column for column in main if column.startswith(("core_", "coap_"))]
    labels = [column for column in main if column.startswith("label_")]
    return main[meta + features + labels], excluded


def characterize_events(raw: pd.DataFrame, events: list[dict], session_id: str) -> list[dict]:
    rows = []
    for event in events:
        pair = frozenset((event["actor_ip"], event["server_ip"]))
        in_pair = pd.Series(
            [frozenset((a, b)) == pair for a, b in zip(raw["ip.src"], raw["ip.dst"])],
            index=raw.index,
        )
        inside = raw.loc[
            in_pair
            & raw["frame.time_epoch"].between(event["start_epoch"], event["end_epoch"], inclusive="both")
        ].copy()
        requests = inside["coap.code"].between(1, 31)
        responses = inside["coap.code"].ge(64)
        request_bytes = float(inside.loc[requests, "frame.len"].sum())
        response_bytes = float(inside.loc[responses, "frame.len"].sum())
        rows.append(
            {
                "meta_session": session_id,
                "label_episode": event["episode_id"],
                "label_attack": event["attack_type"],
                "strategy": event["strategy"],
                "target_rate_pps": event["target_rate_pps"],
                "duration_seconds": event["duration_seconds"],
                "observed_requests": int(requests.sum()),
                "observed_responses": int(responses.sum()),
                "observed_request_wire_bytes": int(request_bytes),
                "observed_response_wire_bytes": int(response_bytes),
                "observed_wire_amplification": response_bytes / request_bytes if request_bytes else 0.0,
                "spoofing": False,
            }
        )
    return rows
