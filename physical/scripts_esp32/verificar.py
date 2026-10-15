#!/usr/bin/env python3
"""Protocol and native firmware tests. --udp also exercises real localhost UDP."""
from pathlib import Path
import argparse
import os
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent


def run(args, **kwargs):
    subprocess.run([str(a) for a in args], check=True, cwd=ROOT, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--udp", action="store_true", help="Añadir prueba con sockets UDP reales")
    args = parser.parse_args()
    env = os.environ.copy()
    env["COAP_TEST_IN_MEMORY"] = "1"
    # Direct execution registers node:test tests, without a subprocess runner.
    run(["node", "tests/server.test.js"], env=env)
    with tempfile.TemporaryDirectory(prefix="coap-tests-") as directory:
        output = Path(directory)
        compiler = shutil.which("g++")
        if not compiler:
            raise SystemExit("g++ no está instalado: quedan pendientes las pruebas C++ nativas.")
        common = [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-I", "firmware/base"]
        run([*common, "tests/wire_test.cpp", "-o", output / "wire"])
        run([output / "wire"])
        for number in range(1, 6):
            run([*common, "-I", "tests/host", f"-DDEVICE_ID={number}", f"-DPROFILE_ID={number}",
                 '-DLAB_WIFI_SSID="lab"', '-DLAB_WIFI_PASSWORD="test-only"',
                 '-DLAB_SERVER_IP="192.168.1.100"',
                 "-DLAB_SESSION_MS=600000",
                 "tests/firmware_test.cpp", "-o", output / f"firmware-{number}"])
            run([output / f"firmware-{number}"])
    if args.udp:
        env.pop("COAP_TEST_IN_MEMORY", None)
        run(["node", "tests/server.test.js"], env=env)
    print("OK: pruebas lógicas. No equivalen a compilar ni probar sobre una placa ESP32-S3.")


if __name__ == "__main__":
    main()
