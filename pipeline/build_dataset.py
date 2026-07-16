#!/usr/bin/env python3
"""Build windowed CoAP data from captured sessions and external event logs."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import coap_features as features


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TESTBED = ROOT / "testbed"
DEFAULT_MANIFEST = DEFAULT_TESTBED / "session_manifest_strong.csv"
DEFAULT_SCHEMA = ROOT / "data" / "dataset_complete_tracking.csv"
DEFAULT_OUTPUT = ROOT / "data" / "rebuilt"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_path(testbed_dir: Path, value: str) -> Path:
    return testbed_dir / Path(value.replace("\\", "/"))


def build(
    manifest_file: Path,
    testbed_dir: Path,
    schema_file: Path,
    output_dir: Path,
    window_seconds: float,
) -> Path:
    manifest = pd.read_csv(manifest_file, dtype=str, keep_default_na=False)
    if manifest.empty:
        raise ValueError("The session manifest is empty.")

    schema = pd.read_csv(schema_file, nrows=0).columns.tolist()
    parts: list[pd.DataFrame] = []
    excluded_parts: list[pd.DataFrame] = []
    interval_rows: list[dict] = []
    characterization_rows: list[dict] = []
    extraction_rows: list[dict] = []
    input_rows: list[dict] = []

    for row in manifest.to_dict("records"):
        session_id = row["session_id"]
        pcap = manifest_path(testbed_dir, row["pcap"])
        event_file = manifest_path(testbed_dir, row["events"])
        if not pcap.exists() or not event_file.exists():
            raise FileNotFoundError(
                f"Missing raw input for {session_id}. Expected {pcap} and {event_file}."
            )

        packets = features.extract_packets(pcap)
        events = features.load_events(event_file)
        windows = features.aggregate(packets, session_id, window_seconds)
        labelled, excluded = features.label_session(windows, events)
        labelled["meta_dataset_source"] = "generated_coap_multidos_loopback_v6.1"
        if not excluded.empty:
            excluded["meta_dataset_source"] = "generated_coap_multidos_loopback_v6.1"

        parts.append(labelled)
        excluded_parts.append(excluded)
        interval_rows.extend(events)
        characterization_rows.extend(
            features.characterize_events(packets, events, session_id)
        )
        extraction_rows.append(
            {
                "session": session_id,
                "coap_packets": len(packets),
                "windows_kept": len(labelled),
                "boundary_windows_excluded": len(excluded),
                "attack_windows": int(labelled["label_binary"].sum()),
            }
        )
        input_rows.append(
            {
                "session": session_id,
                "pcap": str(pcap),
                "pcap_bytes": pcap.stat().st_size,
                "pcap_sha256": sha256(pcap),
                "events": str(event_file),
                "events_sha256": sha256(event_file),
            }
        )
        print(
            f"[ok] {session_id}: packets={len(packets)} windows={len(labelled)} "
            f"excluded={len(excluded)}",
            flush=True,
        )

    complete = pd.concat(parts, ignore_index=True).sort_values(
        ["meta_session", "meta_win_start", "meta_endpoint_a", "meta_endpoint_b"],
        kind="stable",
    )
    missing = [column for column in schema if column not in complete]
    if missing:
        raise ValueError(f"The reconstructed table is missing schema columns: {missing}")
    complete = complete[schema].reset_index(drop=True)

    excluded = pd.concat(excluded_parts, ignore_index=True)
    intervals = pd.DataFrame(interval_rows)
    characterization = pd.DataFrame(characterization_rows)

    output_dir.mkdir(parents=True, exist_ok=True)
    complete_path = output_dir / "dataset_complete_tracking.csv"
    complete.to_csv(complete_path, index=False, encoding="utf-8", float_format="%.9g")
    excluded.to_csv(
        output_dir / "excluded_boundary_windows.csv",
        index=False,
        encoding="utf-8",
        float_format="%.9g",
    )
    intervals.to_csv(output_dir / "attack_intervals.csv", index=False, encoding="utf-8")
    characterization.to_csv(
        output_dir / "episode_characterization.csv",
        index=False,
        encoding="utf-8",
        float_format="%.9g",
    )

    build_manifest = {
        "schema_version": "1.0",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "window_seconds": window_seconds,
        "sessions": int(complete["meta_session"].nunique()),
        "rows": len(complete),
        "class_counts": complete["label_attack"].value_counts().to_dict(),
        "excluded_boundary_windows": len(excluded),
        "tshark": features.tshark_version(),
        "python": sys.version.split()[0],
        "inputs": input_rows,
        "extraction": extraction_rows,
        "output": {
            "file": complete_path.name,
            "bytes": complete_path.stat().st_size,
            "sha256": sha256(complete_path),
        },
    }
    (output_dir / "build_manifest.json").write_text(
        json.dumps(build_manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"[ok] dataset: {complete_path}")
    return complete_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--testbed-dir", type=Path, default=DEFAULT_TESTBED)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--window-seconds", type=float, default=1.0)
    args = parser.parse_args()
    if args.window_seconds != 1.0:
        parser.error("This release uses non-overlapping one-second windows.")
    build(
        args.manifest.resolve(),
        args.testbed_dir.resolve(),
        args.schema.resolve(),
        args.output_dir.resolve(),
        args.window_seconds,
    )


if __name__ == "__main__":
    main()
