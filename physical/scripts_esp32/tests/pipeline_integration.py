"""Explicit localhost-only integration check, including a real TShark PCAP.

Outputs live under .local and are not scientific physical dataset observations.
Run only where Npcap loopback capture is available (Windows preparation host).
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dataset"))
from extract import build


def main():
    directory = ROOT.parent / ".local" / ("pipeline_check_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"))
    directory.mkdir(parents=True)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.2", 0))
        port = probe.getsockname()[1]
    phases, start = [], 0
    for index, kind in enumerate(["baseline", "block2_amplification", "request_flood", "benign_block2_download"]):
        phases.append({"id": f"phase_{index}", "kind": kind,
                       "label": kind if kind in {"block2_amplification", "request_flood"} else "benign",
                       "start_s": start, "duration_s": 6, "rate_rps": 20,
                       "message_type": "NON" if kind == "request_flood" else "CON",
                       "token_policy": "transfer" if kind == "benign_block2_download" else "unique",
                       "block_size": 1024, "block_order": "sequential", "fixed_block": 0})
        start += 6
        phases.append({"id": f"guard_{index}", "kind": "guard", "label": "excluded",
                       "start_s": start, "duration_s": 1, "rate_rps": 0})
        start += 1
    plan = {"schema": 1, "seed": 2026, "duration_s": start, "lanes": 2, "response_timeout_ms": 500, "phases": phases}
    (directory / "plan.json").write_text(json.dumps(plan))
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    server = capture = None
    with (directory / "server.txt").open("w") as server_log, (directory / "capture.txt").open("w") as capture_log:
        try:
            server = subprocess.Popen(["node", str(ROOT / "servidor/server.js"), "--host", "127.0.0.2", "--port", str(port),
                "--session", "test", "--output", str(directory / "server"), "--control-stdin", "--duration", "50"],
                stdin=subprocess.PIPE, stdout=server_log, stderr=subprocess.STDOUT, creationflags=flags)
            time.sleep(.5)
            assert server.poll() is None, "server failed"
            capture = subprocess.Popen(["tshark", "-i", r"\Device\NPF_Loopback", "-f", f"udp port {port}",
                "-s", "0", "-a", "duration:33", "-w", str(directory / "test.pcapng"), "-q"],
                stdout=capture_log, stderr=subprocess.STDOUT, creationflags=flags)
            time.sleep(1)
            subprocess.run(["node", str(ROOT / "actor_coap.js"), "run", "--server", "127.0.0.2", "--port", str(port),
                "--plan", str(directory / "plan.json"), "--session", "test", "--output", str(directory / "actor"),
                "--start-delay", "0", "--clock-note", "localhost integration; shared OS clock"], check=True, creationflags=flags)
            capture.wait(timeout=15)
            assert capture.returncode == 0
        finally:
            if capture is not None and capture.poll() is None:
                capture.terminate(); capture.wait(timeout=5)
            if server is not None and server.poll() is None:
                server.stdin.write(b"STOP\n"); server.stdin.flush()
                server.wait(timeout=5)
    summary = json.loads((directory / "actor/test/summary.json").read_text())
    actor_ip = summary["lanes"][0]["local"]["address"]
    assert actor_ip != "127.0.0.2", "Loopback source is not distinct from server"
    (directory / "clock.json").write_text(json.dumps({"actor_minus_capture_seconds": 0, "uncertainty_seconds": .002,
        "method": "same Windows host clock for actor and Npcap", "evidence": ["localhost integration test only"]}))
    manifest = {"schema": 1, "sessions": [{"session": "integration_only", "pcap": "test.pcapng",
        "server_ip": "127.0.0.2", "server_port": port, "benign_ips": ["127.0.0.3"],
        "dataset_source": "localhost_verification_not_physical_dataset",
        "actor": {"ip": actor_ip, "directory": "actor/test", "clock_file": "clock.json"}}]}
    (directory / "manifest.json").write_text(json.dumps(manifest))
    result = build(directory / "manifest.json", directory / "csv", chunksize=120)
    classes = {"benign", "coap_block2_amplification_flood", "coap_request_flood"}
    for stats in result["sessions"][0]["windows"].values():
        assert set(stats["classes"]) == classes, stats
    truth_counts = result["sessions"][0]["packet_ground_truth_counts"]
    assert truth_counts.get("unmatched_actor_packet", 0) == 0, truth_counts
    report = {"status": "passed", "purpose": "localhost integration only", "directory": str(directory),
              "observations": result["sessions"][0], "window_sizes": result["window_seconds"]}
    (ROOT.parent / "test/pipeline_integracion_validacion.json").write_text(json.dumps(report, indent=2) + "\n")
    print("Integration passed: all three classes at 0.5, 1 and 2 s; every actor packet correlated.")


if __name__ == "__main__":
    main()
