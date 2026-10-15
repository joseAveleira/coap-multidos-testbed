#!/usr/bin/env python3
"""SSH provisioning and measured clock offsets for the authorised lab actor.

Passwords are read from an environment variable or an interactive prompt, never
from configuration files. SSH host keys are pinned in the ignored .local folder.
"""
import argparse
import base64
import getpass
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / ".local/ssh_runtime"))
import paramiko


def connect(host, user):
    state = ROOT.parent / ".local"
    state.mkdir(exist_ok=True)
    known = state / "known_hosts"
    client = paramiko.SSHClient()
    if known.exists():
        client.load_host_keys(str(known))

    class PinFirstKey(paramiko.MissingHostKeyPolicy):
        def missing_host_key(self, ssh, hostname, key):
            fingerprint = base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
            print(f"First connection to {hostname}: {key.get_name()} SHA256:{fingerprint}", flush=True)
            ssh.get_host_keys().add(hostname, key.get_name(), key)
            ssh.save_host_keys(str(known))

    client.set_missing_host_key_policy(PinFirstKey())
    password = os.environ.get("COAP_SSH_PASSWORD")
    try:
        client.connect(hostname=host, username=user, password=password, timeout=10,
                       banner_timeout=10, auth_timeout=10, look_for_keys=True, allow_agent=True)
    except paramiko.AuthenticationException:
        if password:
            raise
        password = getpass.getpass(f"SSH password for {user}@{host}: ")
        client.connect(hostname=host, username=user, password=password, timeout=10,
                       banner_timeout=10, auth_timeout=10, look_for_keys=False, allow_agent=False)
    return client


def command(client, text, timeout=60):
    stdin, stdout, stderr = client.exec_command(text, timeout=timeout)
    stdin.close()
    output = stdout.read().decode("utf-8", "replace")
    error = stderr.read().decode("utf-8", "replace")
    status = stdout.channel.recv_exit_status()
    if status:
        raise RuntimeError(f"Remote command failed ({status}): {error.strip() or output.strip()}")
    return output.strip()


def measure_clock(client, samples=7):
    readings = []
    for _ in range(samples):
        before, mono = time.time(), time.monotonic()
        remote = float(command(client, "python3 -c 'import time; print(time.time_ns()/1e9)'", timeout=15))
        after = time.time()
        elapsed = time.monotonic() - mono
        if abs(after - before - elapsed) > .01:
            raise RuntimeError("Capture host wall clock changed during clock measurement.")
        readings.append({"capture_before": before, "actor_time": remote, "capture_after": after,
                         "round_trip_seconds": after - before,
                         "actor_minus_capture_seconds": remote - (before + after) / 2})
    return {"best": min(readings, key=lambda row: row["round_trip_seconds"]), "samples": readings}


def ensure_base(client):
    """Install only missing Arch packages; do not refresh or upgrade the OS."""
    missing = []
    for executable, package in [("python3", "python"), ("curl", "curl"), ("tar", "tar"), ("xz", "xz")]:
        present = command(client, "command -v " + executable + " || true")
        if not present:
            missing.append(package)
    if not missing:
        return {"installed_packages": [], "status": "dependencies_present"}
    system = command(client, "cat /etc/os-release")
    if not any(line in ('ID=arch', 'ID="arch"') for line in system.splitlines()):
        raise RuntimeError("Missing packages on a non-Arch system; inspect the host before installing")
    password = os.environ.get("COAP_SUDO_PASSWORD") or getpass.getpass("Temporary sudo password (not saved): ")
    stdin, stdout, stderr = client.exec_command("sudo -S -p '' pacman -S --needed --noconfirm " + shlex.join(missing), timeout=600)
    stdin.write(password + "\n"); stdin.flush(); stdin.channel.shutdown_write()
    output, error = stdout.read().decode("utf-8", "replace"), stderr.read().decode("utf-8", "replace")
    status = stdout.channel.recv_exit_status()
    if status:
        raise RuntimeError(f"Package installation failed ({status}): {error.strip() or output.strip()}")
    return {"installed_packages": missing, "status": "installed", "output": output, "diagnostics": error}


def combine_clocks(before, after):
    a, b = before["best"], after["best"]
    difference = abs(a["actor_minus_capture_seconds"] - b["actor_minus_capture_seconds"])
    return {"actor_minus_capture_seconds": (a["actor_minus_capture_seconds"] + b["actor_minus_capture_seconds"]) / 2,
            "uncertainty_seconds": max(a["round_trip_seconds"], b["round_trip_seconds"]) / 2 + difference / 2 + .002,
            "method": "SSH timestamp brackets before/after; minimum RTT samples; endpoint drift included",
            "evidence": {"before": before, "after": after},
            "assumption": "Clock offset remains inside the measured endpoint envelope during the run; reject clock steps."}


def deploy(client, package):
    with client.open_sftp() as sftp:
        home = sftp.normalize(".")
        remote_root = home.rstrip("/") + "/coap-dataset"
        command(client, "mkdir -p " + shlex.quote(remote_root))
        sftp.put(str(package), remote_root + "/actor.zip")
        sftp.put(str(Path(__file__).with_name("prepare_arch.sh")), remote_root + "/prepare_arch.sh")
    expected = hashlib.sha256(package.read_bytes()).hexdigest()
    actual = command(client, "sha256sum " + shlex.quote(remote_root + "/actor.zip")).split()[0]
    if actual != expected:
        raise RuntimeError("Transferred actor ZIP hash mismatch")
    runtime = command(client, "bash " + shlex.quote(remote_root + "/prepare_arch.sh") + " " + shlex.quote(remote_root), timeout=600)
    bundle = remote_root + "/bundles/" + expected[:16]
    command(client, "mkdir -p " + shlex.quote(bundle) + " && python3 -m zipfile -e " + shlex.quote(remote_root + "/actor.zip") + " " + shlex.quote(bundle))
    checks = command(client, "cd " + shlex.quote(bundle) + " && " + shlex.quote(remote_root + "/node") + " tests/actor.test.js")
    return {"remote_root": remote_root, "bundle": bundle, "node": remote_root + "/node",
            "zip_sha256": expected, "runtime": runtime, "offline_tests": checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["probe", "deploy"])
    parser.add_argument("--host", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; use a new filename.")
    with connect(args.host, args.user) as client:
        dependencies = ensure_base(client) if args.action == "deploy" else None
        result = {"host": args.host, "user": args.user,
                  "system": command(client, "uname -a; cat /etc/os-release; command -v node || true; command -v python3; free -m"),
                  "clock_probe": measure_clock(client)}
        if args.action == "deploy":
            result["base_dependencies"] = dependencies
            result.update(deploy(client, ROOT.parent / "recursos/actor_coap_portable.zip"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
