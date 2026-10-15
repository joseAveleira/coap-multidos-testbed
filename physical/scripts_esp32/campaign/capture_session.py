#!/usr/bin/env python3
"""One physical session: Windows server/PCAP + SSH actor + external labels.

The declared clients must be observed before the actor sends a campaign.
All outputs, including failed attempts, are retained in a new directory.
"""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import shlex
import subprocess
import time

from remote import ROOT, command, combine_clocks, connect, measure_clock

HIDDEN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def save(path, obj):
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def capture_command(interface, seconds, target):
    return ["tshark", "-i", interface, "-f", "udp port 5683", "-s", "0", "-a", f"duration:{seconds}", "-w", str(target), "-q"]


def observed_devices(pcap, config):
    result = subprocess.run(["tshark", "-n", "-r", str(pcap), "-Y", "coap.code == 1 && udp.dstport == 5683",
                             "-T", "fields", "-e", "eth.src", "-e", "ip.src", "-e", "ip.dst"],
                            capture_output=True, text=True, check=True, creationflags=HIDDEN)
    observed = {}
    for line in result.stdout.splitlines():
        columns = line.split("\t")
        if len(columns) == 3 and columns[2] == config["server_ip"]:
            observed.setdefault(columns[0].lower(), set()).add(columns[1])
    devices = []
    for device in config["devices"]:
        addresses = observed.get(device["mac"].lower(), set())
        if len(addresses) != 1:
            raise RuntimeError(f"Client {device['device_id']} has no unique observed IP: {sorted(addresses)}. Keep its PCAP and check power/Wi-Fi before running attacks.")
        devices.append({**device, "observed_ipv4": next(iter(addresses))})
    if len({d["observed_ipv4"] for d in devices}) != len(devices):
        raise RuntimeError("Two physical identities share one observed IP")
    return devices


def run(config, deployment, plan_path, session, output):
    if not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*", session):
        raise ValueError("Invalid session name")
    if config["actor_ip"] != deployment["host"] or config["actor_user"] != deployment["user"]:
        raise ValueError("Deployment host/user does not match the testbed")
    # Invoke the actor's actual validator before starting any local service.
    subprocess.run(["node", str(ROOT / "actor_coap.js"), "inspect", "--plan", str(plan_path)], check=True,
                   stdout=subprocess.DEVNULL, creationflags=HIDDEN)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    seconds = math.ceil(plan["duration_s"])
    output.mkdir(parents=True, exist_ok=False)
    save(output / "testbed.json", config)
    save(output / "plan.json", plan)
    save(output / "deployment.json", deployment)
    record = {"session": session, "created_utc": datetime.now(timezone.utc).isoformat(), "status": "preparing"}
    server = capture = ssh = remote_channel = None
    remote_pid = None
    handles = []
    try:
        def stream(name):
            handle = (output / name).open("w", encoding="utf-8")
            handles.append(handle)
            return handle
        server = subprocess.Popen(["node", str(ROOT / "servidor/server.js"), "--host", "0.0.0.0",
                "--session", session, "--seed", str(plan["seed"]), "--duration", str(seconds + 150),
                "--output", str(output / "server"), "--control-stdin"], stdin=subprocess.PIPE,
                stdout=stream("server.stdout.txt"), stderr=stream("server.stderr.txt"), creationflags=HIDDEN)
        time.sleep(.5)
        if server.poll() is not None:
            raise RuntimeError("Local server failed to start; inspect server.stderr.txt")
        inventory = output / "inventory.pcapng"
        # A client may still be backing off a CON request sent while the server
        # was stopped. Observe beyond the retransmission schedule before
        # deciding that a board is absent.
        print("Observing physical clients for 60 s before starting the actor...", flush=True)
        subprocess.run(capture_command(config["capture_interface"], 60, inventory), check=True,
                       stdout=stream("inventory.stdout.txt"), stderr=stream("inventory.stderr.txt"), creationflags=HIDDEN)
        devices = observed_devices(inventory, config)
        record["devices_observed_before_run"] = devices
        print(f"Observed {len(devices)} physical clients.", flush=True)
        ssh = connect(config["actor_ip"], config["actor_user"])
        clock_before = measure_clock(ssh)
        remote_plan = deployment["remote_root"] + "/plans/" + session + ".json"
        command(ssh, "mkdir -p " + shlex.quote(deployment["remote_root"] + "/plans"))
        with ssh.open_sftp() as sftp:
            sftp.put(str(output / "plan.json"), remote_plan)
        cap_command = capture_command(config["capture_interface"], seconds + 35, output / "traffic.pcapng")
        capture = subprocess.Popen(cap_command, stdout=stream("tshark.stdout.txt"), stderr=stream("tshark.stderr.txt"), creationflags=HIDDEN)
        time.sleep(1.5)
        if capture.poll() is not None:
            raise RuntimeError("Capture failed before actor start")
        record["capture_command"] = cap_command
        remote_output = deployment["remote_root"] + "/records"
        actor_args = [deployment["node"], "actor_coap.js", "run", "--server", config["server_ip"],
                      "--plan", remote_plan, "--session", session, "--output", remote_output,
                      "--clock-note", "SSH timestamp brackets before and after; see capture-side clock.json"]
        shell = "cd " + shlex.quote(deployment["bundle"]) + " && printf '%s\\n' $$ && exec " + shlex.join(actor_args)
        # The account may use fish or another non-POSIX login shell. Execute
        # PID reporting and exec explicitly in bash, matching shlex quoting.
        stdin, stdout, stderr = ssh.exec_command("bash -c " + shlex.quote(shell), timeout=seconds + 50)
        stdin.close()
        remote_channel = stdout.channel
        pid_bytes = b""
        while not pid_bytes.endswith(b"\n") and len(pid_bytes) < 32:
            byte = remote_channel.recv(1)
            if not byte:
                break
            pid_bytes += byte
        pid_text = pid_bytes.decode("ascii", "replace").strip()
        if not pid_text.isdigit():
            error = remote_channel.recv_stderr(8192).decode("utf-8", "replace") if remote_channel.recv_stderr_ready() else ""
            stream("actor.launch_error.txt").write(error)
            raise RuntimeError(f"Remote actor process did not report its PID: {pid_text!r}; {error.strip()}")
        remote_pid = int(pid_text)
        record.update(status="running", remote_pid=remote_pid)
        actor_out, actor_err = stream("actor.stdout.txt"), stream("actor.stderr.txt")
        deadline = time.monotonic() + seconds + 30
        capture_clock_start, capture_mono_start = time.time(), time.monotonic()
        while not remote_channel.exit_status_ready():
            if abs((time.time() - capture_clock_start) - (time.monotonic() - capture_mono_start)) > .05:
                raise RuntimeError("Capture host clock changed during the campaign; reconcile timestamps before labelling")
            if capture.poll() is not None or server.poll() is not None:
                raise RuntimeError("Capture or server stopped before the actor finished")
            if time.monotonic() > deadline:
                raise RuntimeError("Actor exceeded its planned duration and startup allowance")
            if remote_channel.recv_ready():
                data = remote_channel.recv(65536).decode("utf-8", "replace")
                actor_out.write(data); actor_out.flush()
                print(data, end="", flush=True)
            if remote_channel.recv_stderr_ready():
                actor_err.write(remote_channel.recv_stderr(65536).decode("utf-8", "replace")); actor_err.flush()
            time.sleep(.1)
        # Drain the remaining channel output after exit.
        actor_out.write(stdout.read().decode("utf-8", "replace"))
        actor_err.write(stderr.read().decode("utf-8", "replace"))
        code = remote_channel.recv_exit_status()
        record["actor_exit_code"] = code
        clock_after = measure_clock(ssh)
        save(output / "clock.json", combine_clocks(clock_before, clock_after))
        actor_dir = output / "actor"
        actor_dir.mkdir()
        with ssh.open_sftp() as sftp:
            for name in ["manifest.json", "plan.json", "events.jsonl", "traffic.jsonl", "summary.json", "sha256.json"]:
                sftp.get(remote_output + "/" + session + "/" + name, str(actor_dir / name))
        # A preflight failure can end the actor while most of the planned
        # capture is still ahead. Preserve the actual failure before waiting
        # for TShark; the finally block closes that incomplete capture.
        if code:
            raise RuntimeError(f"Actor exited with code {code}; inspect actor/summary.json and actor.stderr.txt; raw evidence retained")
        capture.wait(timeout=60)
        if capture.returncode:
            raise RuntimeError(f"Actor/capture exit codes: {code}/{capture.returncode}; raw evidence retained")
        record["devices_observed_in_campaign"] = observed_devices(output / "traffic.pcapng", config)
        if record["devices_observed_in_campaign"] != devices:
            raise RuntimeError("Client IP identities changed between inventory and campaign; reconcile before labelling")
        save(output / "dataset_manifest.json", {"schema": 1, "sessions": [{"session": session,
             "pcap": "traffic.pcapng", "server_ip": config["server_ip"],
             "benign_ips": [d["observed_ipv4"] for d in devices],
             "actor": {"ip": config["actor_ip"], "directory": "actor", "clock_file": "clock.json"},
             "purpose": "physical_network_campaign"}]})
        record["status"] = "captured_pending_extraction"
    except BaseException as error:
        record.update(status="failed", error=str(error))
        raise
    finally:
        if remote_channel is not None and not remote_channel.exit_status_ready() and remote_pid is not None:
            try:
                command(ssh, f"kill -INT {remote_pid}", timeout=10)
            except Exception as error:
                record["remote_stop_error"] = str(error)
        if capture is not None and capture.poll() is None:
            capture.terminate()
            capture.wait(timeout=10)
            record["capture_forced_stop"] = True
        if server is not None and server.poll() is None:
            try:
                server.stdin.write(b"STOP\n"); server.stdin.flush()
                server.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                server.terminate(); server.wait(timeout=10)
                record["server_forced_stop"] = True
        if ssh is not None:
            ssh.close()
        for handle in handles:
            handle.close()
        record["finished_utc"] = datetime.now(timezone.utc).isoformat()
        save(output / "execution.json", record)
    print(f"Capture and actor records saved: {output}", flush=True)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--deployment", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(json.loads(args.config.read_text()), json.loads(args.deployment.read_text()),
        args.plan.resolve(), args.session, args.output.resolve())


if __name__ == "__main__":
    main()
