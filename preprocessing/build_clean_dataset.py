#!/usr/bin/env python3
"""Create the clean multiclass modelling table from the complete dataset."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "dataset_complete_tracking.csv"
DEFAULT_OUTPUT = ROOT / "data" / "rebuilt" / "dataset_clean_multiclass.csv"

FEATURES = [
    "core_bytes_per_s",
    "core_mean_len",
    "core_std_len",
    "core_mean_iat",
    "core_std_iat",
    "core_active_span_frac",
    "coap_req_per_s",
    "coap_resp_per_s",
    "coap_non_per_s",
    "coap_request_frac",
    "coap_con_frac",
    "coap_log_resp_req",
    "coap_mean_payload_len",
    "coap_block2_req_per_s",
    "coap_block2_resp_per_s",
    "coap_block2_frac",
    "coap_block2_more_resp_frac",
    "coap_block2_mean_number",
    "coap_block2_unique_numbers",
    "coap_block2_sequential_req_frac",
    "coap_block2_repeated_req_frac",
    "coap_block2_req_unique_token_frac",
    "coap_block2_log_resp_req_bytes",
]

TARGET_MAP = {
    "benign": 0,
    "coap_block2_amplification_flood": 1,
    "coap_request_flood": 2,
}


def build_clean(frame: pd.DataFrame) -> pd.DataFrame:
    required = ["meta_session", "label_attack", *FEATURES]
    missing = [column for column in required if column not in frame]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")
    if frame[required].isna().to_numpy().any():
        raise ValueError("The retained fields contain missing values.")
    numeric = frame[FEATURES].to_numpy(dtype=float)
    if not np.isfinite(numeric).all():
        raise ValueError("The retained features contain non-finite values.")
    unknown = sorted(set(frame["label_attack"]) - set(TARGET_MAP))
    if unknown:
        raise ValueError(f"Unknown labels: {unknown}")

    clean = frame[["meta_session", *FEATURES]].copy()
    clean["target"] = frame["label_attack"].map(TARGET_MAP).astype(int)
    return clean


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    source = pd.read_csv(args.input)
    clean = build_clean(source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    clean.to_csv(args.output, index=False, encoding="utf-8", float_format="%.9g")
    print(
        f"[ok] {args.output}: rows={len(clean)} predictors={len(FEATURES)} "
        f"classes={clean['target'].value_counts().sort_index().to_dict()}"
    )


if __name__ == "__main__":
    main()
