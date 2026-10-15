#!/usr/bin/env python3
"""Create an explicitly documented chronological PCAPNG; preserve the raw input."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess

from extract import read_json, sha256


def packet_inventory(path):
    """Hash packet bytes, lengths, interface ID and original timestamp ticks.

    A sorted multiset of hashes verifies packet preservation even when frames
    move. This testbed uses PCAPNG enhanced packet blocks; other packet block
    encodings fail explicitly rather than being silently skipped.
    """
    digests, ticks, previous, backsteps = [], None, None, []
    endian = "<"
    with path.open("rb") as f:
        while header := f.read(8):
            if len(header) != 8:
                raise ValueError("Truncated PCAPNG block header")
            if header[:4] == b"\x0a\x0d\x0d\x0a":
                bom = f.read(4)
                if bom not in (b"\x4d\x3c\x2b\x1a", b"\x1a\x2b\x3c\x4d"):
                    raise ValueError("Unknown PCAPNG byte order")
                endian = "<" if bom == b"\x4d\x3c\x2b\x1a" else ">"
                length = struct.unpack(endian + "I", header[4:])[0]
                body = bom + f.read(length - 12)
            else:
                length = struct.unpack(endian + "I", header[4:])[0]
                body = f.read(length - 8)
            if length < 12 or len(body) != length - 8 or struct.unpack(endian + "I", body[-4:])[0] != length:
                raise ValueError("Invalid PCAPNG block length")
            kind = struct.unpack(endian + "I", header[:4])[0]
            if kind == 1:
                if ticks is not None:
                    raise ValueError("Ordering validator expects one capture interface")
                resolution = 1e-6
                cursor = 8
                while cursor + 4 <= len(body) - 4:
                    code, size = struct.unpack_from(endian + "HH", body, cursor)
                    if not code:
                        break
                    if code == 9:
                        value = body[cursor + 4]
                        resolution = (2 ** -(value & 127)) if value & 128 else 10 ** -value
                    cursor += 4 + ((size + 3) // 4) * 4
                ticks = resolution
            elif kind == 6:
                interface, high, low, captured, original = struct.unpack_from(endian + "IIIII", body)
                if ticks is None or interface != 0 or captured > len(body) - 24:
                    raise ValueError("Unexpected interface or packet size")
                timestamp = high * 2 ** 32 + low
                if previous is not None and timestamp < previous:
                    backsteps.append((previous - timestamp) * ticks)
                previous = timestamp
                digest = hashlib.sha256(struct.pack(">IIIII", interface, high, low, captured, original) + body[20:20 + captured]).digest()
                digests.append(digest)
            elif kind in (2, 3):
                raise ValueError("Legacy/simple packet blocks are not supported by this validator")
    if not digests:
        raise ValueError("No enhanced packet blocks found")
    return {"packets": len(digests), "timestamp_tick_seconds": ticks,
            "adjacent_timestamp_backsteps": len(backsteps), "maximum_backstep_seconds": max(backsteps, default=0),
            "packet_timestamp_multiset_sha256": hashlib.sha256(b"".join(sorted(digests))).hexdigest()}


def order(capture):
    manifest_path = capture / "dataset_manifest.json"
    manifest = read_json(manifest_path)
    if len(manifest["sessions"]) != 1:
        raise ValueError("Order one physical acquisition session at a time")
    session = manifest["sessions"][0]
    original = capture / session["pcap"]
    target = capture / (original.stem + "_chronological.pcapng")
    output_manifest = capture / "dataset_chronological_manifest.json"
    if target.exists() or output_manifest.exists():
        raise FileExistsError("Chronological output already exists; no evidence is overwritten")
    raw_hash, before = sha256(original), packet_inventory(original)
    command = ["reordercap", str(original), str(target)]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    after = packet_inventory(target)
    if sha256(original) != raw_hash or after["adjacent_timestamp_backsteps"] or any(
            before[key] != after[key] for key in ["packets", "timestamp_tick_seconds", "packet_timestamp_multiset_sha256"]):
        raise ValueError("Chronological derivative failed packet/timestamp preservation checks")
    provenance = {"method": "reordercap; timestamp sort only, no timestamp adjustment", "command": command,
                  "diagnostic": result.stdout + result.stderr, "original_file": original.name,
                  "original_sha256": raw_hash, "ordered_sha256": sha256(target), "before": before, "after": after}
    session["pcap"] = target.name
    session["timestamp_ordering"] = provenance
    output_manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(provenance, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    order(parser.parse_args().capture.resolve())
