#!/usr/bin/env python3
"""Build the field dictionary for the published complete and clean tables."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from build_clean_dataset import FEATURES


ROOT = Path(__file__).resolve().parents[1]

DESCRIPTIONS = {
    "meta_dataset_source": "Logical source of the observation.",
    "meta_session": "Independent session used for grouped evaluation; never a predictor.",
    "meta_capture": "Capture identifier retained for audit only.",
    "meta_win_idx": "Zero-based window index within the session.",
    "meta_endpoint_a": "First endpoint of the unordered conversation pair.",
    "meta_endpoint_b": "Second endpoint of the unordered conversation pair.",
    "meta_n_frames": "Number of CoAP frames in the window.",
    "meta_win_start": "Window start in seconds relative to the capture.",
    "meta_win_end": "Window end in seconds relative to the capture.",
    "meta_window_seconds": "Window duration in seconds.",
    "meta_time_block_60s": "Coarse time block retained for audit only.",
    "core_pkts_per_s": "CoAP frame rate in the window.",
    "core_bytes_per_s": "Total captured frame bytes per second.",
    "core_mean_len": "Mean captured frame length in bytes.",
    "core_std_len": "Population standard deviation of frame length.",
    "core_mean_iat": "Mean inter-arrival time between frames.",
    "core_std_iat": "Population standard deviation of inter-arrival time.",
    "core_active_span_frac": "Fraction of the window between its first and last frame.",
    "coap_req_per_s": "CoAP request rate.",
    "coap_resp_per_s": "CoAP response rate.",
    "coap_empty_per_s": "Empty CoAP message rate.",
    "coap_con_per_s": "Confirmable CoAP message rate.",
    "coap_non_per_s": "Non-confirmable CoAP message rate.",
    "coap_ack_per_s": "Acknowledgement message rate.",
    "coap_rst_per_s": "Reset message rate.",
    "coap_observe_per_s": "Rate of messages containing the Observe option.",
    "coap_notification_per_s": "Observe notification rate.",
    "coap_request_frac": "Fraction of frames that are CoAP requests.",
    "coap_response_frac": "Fraction of frames that are CoAP responses.",
    "coap_empty_ack_frac": "Fraction of frames that are empty acknowledgements.",
    "coap_con_frac": "Fraction of frames that are confirmable messages.",
    "coap_ack_frac": "Fraction of frames that are acknowledgements.",
    "coap_observe_frac": "Fraction of frames containing the Observe option.",
    "coap_notification_frac": "Fraction of frames that are Observe notifications.",
    "coap_success_resp_frac": "Fraction of responses with a success code.",
    "coap_resp_balance": "Responses divided by the sum of requests and responses.",
    "coap_log_resp_req": "Difference between log1p response and request counts.",
    "coap_payload_bytes_per_s": "CoAP payload bytes per second.",
    "coap_mean_payload_len": "Mean CoAP payload length in bytes.",
    "coap_method_entropy": "Shannon entropy of request methods.",
    "coap_distinct_methods": "Number of distinct request methods.",
    "coap_block2_per_s": "Rate of messages containing the Block2 option.",
    "coap_block2_req_per_s": "Block2 request rate.",
    "coap_block2_resp_per_s": "Block2 response rate.",
    "coap_block2_frac": "Fraction of frames containing the Block2 option.",
    "coap_block2_more_resp_frac": "Fraction of Block2 responses with the M bit set.",
    "coap_block2_mean_number": "Mean requested Block2 number.",
    "coap_block2_unique_numbers": "Number of distinct requested Block2 numbers.",
    "coap_block2_sequential_req_frac": "Fraction of sequential Block2 request transitions, including 31 to 0.",
    "coap_block2_repeated_req_frac": "Fraction of repeated Block2 numbers among requests.",
    "coap_block2_req_unique_token_frac": "Distinct-token fraction among Block2 requests.",
    "coap_block2_payload_bytes_per_s": "Block2 response payload bytes per second.",
    "coap_block2_log_resp_req_bytes": "Difference between log1p Block2 response and request wire bytes.",
    "label_binary": "Binary ground truth: zero for benign and one for either attack.",
    "label_attack": "Text ground-truth class.",
    "label_episode": "Externally recorded attack episode identifier.",
    "label_overlap_fraction": "Fraction of the window covered by its assigned event.",
    "label_confidence": "Ground-truth confidence level.",
    "label_source": "Source used to assign the label.",
    "label_attack_strategy": "Scheduled workload variant within the attack class.",
}


def role(column: str) -> str:
    if column == "meta_session":
        return "evaluation_group"
    if column.startswith("meta_"):
        return "audit_metadata"
    if column.startswith("label_"):
        return "ground_truth"
    if column in FEATURES:
        return "predictor"
    return "derived_not_selected"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input", type=Path, default=ROOT / "data" / "dataset_complete_tracking.csv"
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "data" / "data_dictionary.csv"
    )
    args = parser.parse_args()

    frame = pd.read_csv(args.input)
    rows = []
    for column in frame.columns:
        block = column.split("_", 1)[0]
        rows.append(
            {
                "column": column,
                "block": block,
                "dtype": str(frame[column].dtype),
                "role": role(column),
                "in_clean_dataset": column in FEATURES or column == "meta_session",
                "description": DESCRIPTIONS[column],
            }
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(args.output, index=False, encoding="utf-8")
    print(f"[ok] {args.output}: fields={len(rows)} predictors={len(FEATURES)}")


if __name__ == "__main__":
    main()
