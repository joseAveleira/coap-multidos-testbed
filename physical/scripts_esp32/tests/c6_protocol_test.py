"""Exercise the C6 MicroPython wire codec against the actual Node CoAP server."""
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "firmware/c6_micropython"))
from coap_wire import request, decode, validate_response


def main():
    output = ROOT.parent / ".local" / ("c6_protocol_" + str(time.time_ns()))
    output.mkdir(parents=True)
    with (output / "server.stdout.txt").open("w") as log, (output / "server.stderr.txt").open("w") as err:
        server = subprocess.Popen(["node", str(ROOT / "servidor/server.js"), "--host", "127.0.0.1",
             "--duration", "15", "--session", "c6_codec", "--seed", "2026", "--output", str(output), "--control-stdin"],
             stdin=subprocess.PIPE, stdout=log, stderr=err, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            time.sleep(.5)
            assert server.poll() is None
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as channel:
                channel.settimeout(3)
                token = b"c6t5"
                channel.sendto(request(1, token), ("127.0.0.1", 5683))
                reply = decode(channel.recvfrom(1500)[0])
                validate_response(reply, 1)
                assert reply["token"] == token
                content, etag = bytearray(), None
                for block in range(32):
                    channel.sendto(request(block + 2, token, "large", block, True), ("127.0.0.1", 5683))
                    reply = decode(channel.recvfrom(1500)[0])
                    validate_response(reply, block + 2, block, True)
                    assert reply["token"] == token
                    assert etag in (None, reply["etag"])
                    etag = reply["etag"]
                    content.extend(reply["payload"])
                assert len(content) == 32768
                expected = bytes(65 + ((i + 2026) % 26) for i in range(32768))
                assert content == expected
            malformed = [b"", b"\x59\x45\0\0", b"\x54\x45\0\0",
                         b"\x40\x45\0\0\xff", b"\x40\x45\0\0\xf0",
                         b"\x40\x45\0\0\xdd\0"]
            for packet in malformed:
                try:
                    decode(packet)
                except ValueError:
                    continue
                raise AssertionError("Malformed packet accepted")
            report = {"status": "passed", "scope": "C6 codec and actual Node localhost UDP; not physical acquisition",
                      "valid_requests": 33, "download_bytes": len(content),
                      "download_sha256": hashlib.sha256(content).hexdigest(),
                      "malformed_packets_rejected": len(malformed),
                      "codec_sha256": hashlib.sha256((ROOT / "firmware/c6_micropython/coap_wire.py").read_bytes()).hexdigest()}
            (ROOT.parent / "test/c6_protocol_validation.json").write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps(report))
        finally:
            if server.poll() is None:
                server.stdin.write(b"STOP\n"); server.stdin.flush(); server.wait(timeout=5)


if __name__ == "__main__":
    main()
