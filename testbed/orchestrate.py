#!/usr/bin/env python3
"""Captura y ejecuta sesiones reproducibles del testbed CoAP Block2 local."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent
CAPTURES = HERE / "captures"
EVENTS = HERE / "events"
METRICS = HERE / "metrics"
LOGS = HERE / "logs"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def version(command: list[str]) -> str:
    result = subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True
    )
    return result.stdout.splitlines()[0].strip()


def loopback_interface() -> str:
    result = subprocess.run(
        ["tshark", "-D"], capture_output=True, text=True, encoding="utf-8", errors="replace", check=True
    )
    for line in result.stdout.splitlines():
        if "NPF_Loopback" in line:
            match = re.match(r"\s*(\d+)\.", line)
            if match:
                return match.group(1)
    raise RuntimeError("No se encontró el adaptador Npcap de loopback en `tshark -D`.")


def move_generated(session_id: str, staging: Path) -> tuple[Path, Path, Path]:
    event_source = staging / f"{session_id}.events.jsonl"
    probe_source = staging / f"{session_id}.probes.csv"
    summary_source = staging / f"{session_id}.summary.json"
    event_target = EVENTS / event_source.name
    probe_target = METRICS / probe_source.name
    summary_target = METRICS / summary_source.name
    event_source.replace(event_target)
    probe_source.replace(probe_target)
    summary_source.replace(summary_target)
    return event_target, probe_target, summary_target


def run_session(profile: str, number: int, interface: str, overwrite: bool) -> dict:
    session_id = f"{profile}_{number:02d}"
    if profile == "full":
        seed, third_octet = 6100 + number, number
    elif profile == "strong":
        seed, third_octet = 7100 + number, 100 + number
    else:
        seed, third_octet = 6000 + number, 200 + number
    server_ip = f"127.20.{third_octet}.1"
    capture_path = CAPTURES / f"{session_id}.pcapng"
    event_path = EVENTS / f"{session_id}.events.jsonl"
    probe_path = METRICS / f"{session_id}.probes.csv"
    summary_path = METRICS / f"{session_id}.summary.json"
    if not overwrite and all(path.exists() for path in (capture_path, event_path, probe_path, summary_path)):
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        return {
            "session_id": session_id,
            "profile": profile,
            "seed": seed,
            "server_ip": server_ip,
            "pcap": str(capture_path.relative_to(HERE)),
            "events": str(event_path.relative_to(HERE)),
            "probes": str(probe_path.relative_to(HERE)),
            "summary": str(summary_path.relative_to(HERE)),
            "pcap_bytes": capture_path.stat().st_size,
            "pcap_sha256": sha256(capture_path),
            "event_count": summary["episode_count"],
            "status": "reused",
        }

    for target in (CAPTURES, EVENTS, METRICS, LOGS):
        target.mkdir(parents=True, exist_ok=True)
    staging = HERE / ".staging"
    staging.mkdir(parents=True, exist_ok=True)
    for path in (capture_path, event_path, probe_path, summary_path):
        if path.exists():
            path.unlink()

    capture_seconds = {"smoke": 13, "full": 49, "strong": 74}[profile]
    tshark_command = [
        "tshark",
        "-i",
        interface,
        "-f",
        "udp port 5683",
        "-a",
        f"duration:{capture_seconds}",
        "-w",
        str(capture_path),
        "-q",
    ]
    creation_flags = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
    tshark_log = LOGS / f"{session_id}.tshark.log"
    node_log = LOGS / f"{session_id}.node.log"
    with tshark_log.open("w", encoding="utf-8") as capture_log:
        capture = subprocess.Popen(
            tshark_command,
            stdout=capture_log,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=creation_flags,
        )
        # En Windows/Npcap la apertura del adaptador puede tardar bastante. El
        # PCAPNG aparece cuando dumpcap ya ha escrito su cabecera; iniciar Node
        # antes de ese punto produciría una captura vacía aunque hubiera tráfico.
        ready_deadline = time.monotonic() + 60
        while time.monotonic() < ready_deadline:
            if capture.poll() is not None:
                raise RuntimeError(f"TShark terminó antes de capturar; revisar {tshark_log}")
            if capture_path.exists() and capture_path.stat().st_size >= 128:
                break
            time.sleep(0.25)
        else:
            capture.terminate()
            raise TimeoutError("TShark no dejó preparada la captura en 60 segundos.")
        time.sleep(0.75)
        node_command = [
            "node",
            str(HERE / "run_session.js"),
            "--session",
            session_id,
            "--seed",
            str(seed),
            "--profile",
            profile,
            "--server-ip",
            server_ip,
            "--port",
            "5683",
            "--output-dir",
            str(staging),
        ]
        node_result = subprocess.run(
            node_command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout={"smoke": 60, "full": 70, "strong": 105}[profile],
            creationflags=creation_flags,
        )
        node_log.write_text(node_result.stdout + node_result.stderr, encoding="utf-8")
        if node_result.returncode:
            capture.terminate()
            capture.wait(timeout=10)
            raise RuntimeError(f"Falló Node en {session_id}; revisar {node_log}")
        capture.wait(timeout=capture_seconds + 10)

    event_path, probe_path, summary_path = move_generated(session_id, staging)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if not capture_path.exists() or capture_path.stat().st_size == 0:
        raise RuntimeError(f"La captura {capture_path} está vacía.")
    return {
        "session_id": session_id,
        "profile": profile,
        "seed": seed,
        "server_ip": server_ip,
        "pcap": str(capture_path.relative_to(HERE)),
        "events": str(event_path.relative_to(HERE)),
        "probes": str(probe_path.relative_to(HERE)),
        "summary": str(summary_path.relative_to(HERE)),
        "pcap_bytes": capture_path.stat().st_size,
        "pcap_sha256": sha256(capture_path),
        "event_count": summary["episode_count"],
        "status": "generated",
    }


def write_manifest(rows: list[dict], profile: str) -> None:
    manifest_csv = HERE / f"session_manifest_{profile}.csv"
    with manifest_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    manifest = {
        "schema_version": "1.0",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "isolated_local_coap_multidos_testbed",
        "attacks": (
            ["coap_block2_amplification_flood", "coap_request_flood"]
            if profile == "strong"
            else ["coap_block2_amplification_flood"]
        ),
        "reflection": False,
        "interface": "Npcap loopback",
        "node": version(["node", "--version"]),
        "tshark": version(["tshark", "--version"]),
        "python": sys.version.split()[0],
        "sessions": rows,
    }
    (HERE / f"generation_manifest_{profile}.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("smoke", "full", "strong"), default="smoke")
    parser.add_argument("--sessions", type=int, default=1)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if args.sessions < 1:
        parser.error("--sessions debe ser positivo")
    interface = loopback_interface()
    print(f"[info] interfaz loopback tshark={interface}", flush=True)
    rows = []
    for number in range(1, args.sessions + 1):
        print(f"[info] iniciando {args.profile}_{number:02d}", flush=True)
        row = run_session(args.profile, number, interface, args.overwrite)
        rows.append(row)
        print(
            f"[ok] {row['session_id']} pcap={row['pcap_bytes']} bytes "
            f"episodios={row['event_count']} ({row['status']})",
            flush=True,
        )
    write_manifest(rows, args.profile)
    print(f"[ok] manifiesto: {HERE / f'session_manifest_{args.profile}.csv'}", flush=True)


if __name__ == "__main__":
    main()
