#!/usr/bin/env python3
"""Validate the published complete and clean CoAP tables."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

from build_clean_dataset import FEATURES, build_clean


ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    args = parser.parse_args()

    complete = pd.read_csv(args.data_dir / "dataset_complete_tracking.csv")
    clean = pd.read_csv(args.data_dir / "dataset_clean_multiclass.csv")
    require(complete.shape == (3797, 60), f"Unexpected complete shape: {complete.shape}")
    require(clean.shape == (3797, 25), f"Unexpected clean shape: {clean.shape}")
    require(not complete.isna().to_numpy().any(), "Complete data contain missing values.")
    require(not clean.isna().to_numpy().any(), "Clean data contain missing values.")
    require(
        np.isfinite(clean[FEATURES].to_numpy(dtype=float)).all(),
        "Clean predictors contain non-finite values.",
    )
    require(clean["meta_session"].nunique() == 15, "Expected 15 sessions.")
    require(
        clean["target"].value_counts().sort_index().to_dict() == {0: 3436, 1: 253, 2: 108},
        "Unexpected target distribution.",
    )
    per_session = clean.groupby("meta_session")["target"].nunique()
    require(per_session.eq(3).all(), "Every session must contain all three classes.")

    rebuilt = build_clean(complete)
    require(
        rebuilt.equals(clean),
        "The clean table is not an exact reconstruction of the complete table.",
    )

    duplicate_pairs = []
    for index, left in enumerate(FEATURES):
        for right in FEATURES[index + 1 :]:
            if clean[left].equals(clean[right]):
                duplicate_pairs.append((left, right))
    require(not duplicate_pairs, f"Exact duplicate predictors found: {duplicate_pairs}")

    dictionary = pd.read_csv(args.data_dir / "data_dictionary.csv")
    require(
        dictionary["column"].tolist() == complete.columns.tolist(),
        "The data dictionary does not match the complete table schema.",
    )
    documented_clean = dictionary.loc[
        dictionary["in_clean_dataset"].astype(bool), "column"
    ].tolist()
    require(
        documented_clean == ["meta_session", *FEATURES],
        "The data dictionary does not match the clean table fields.",
    )

    sample = args.data_dir / "example" / "smoke_01.pcapng"
    require(sample.exists() and sample.stat().st_size > 128, "The example PCAPNG is missing.")
    if shutil.which("tshark"):
        result = subprocess.run(
            ["tshark", "-r", str(sample), "-Y", "coap", "-T", "fields", "-e", "frame.number"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        require(bool(result.stdout.strip()), "TShark found no CoAP frames in the example capture.")

    print("[ok] published artifacts are internally consistent")
    print(f"[ok] complete={complete.shape} clean={clean.shape} sessions=15 predictors={len(FEATURES)}")


if __name__ == "__main__":
    main()
