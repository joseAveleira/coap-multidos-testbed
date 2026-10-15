#!/usr/bin/env python3
"""Generate five standalone Arduino sketches from the maintained shared source."""
from pathlib import Path
import argparse

ROOT = Path(__file__).resolve().parent


def generate(force=False, devices=range(1, 6)):
    base = ROOT / "firmware" / "base"
    for number in devices:
        name = f"esp32_{number:02d}"
        dest = ROOT / "firmware" / name
        dest.mkdir(parents=True, exist_ok=True)
        files = {p.name: p.read_bytes() for p in base.glob("*.h") if p.name != "config_local.h"}
        board = "ESP32-C6 (nucleo Arduino 3.x)" if number == 5 else "ESP32-S3 Mini"
        files[f"{name}.ino"] = (
            f"// {board} numero {number}. Perfil modificable independientemente.\n"
            f"#define DEVICE_ID {number}\n#define PROFILE_ID {number}\n"
            '#include "client.h"\n\nExperiment experiment;\n'
            'void setup() { experiment.setup(); }\n'
            'void loop() { experiment.loop(); }\n'
        ).encode()
        for filename, data in files.items():
            target = dest / filename
            if target.exists() and target.read_bytes() != data and not force:
                raise SystemExit(f"{target} tiene cambios. No se sobrescribe; usa --force si procede.")
            target.write_bytes(data)
        print(dest.relative_to(ROOT))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Reemplazar .ino/.h generados; conserva config_local.h")
    parser.add_argument("--device", type=int, choices=range(1, 6), action="append", help="Generar solo esta placa; se puede repetir")
    args = parser.parse_args()
    generate(args.force, args.device or range(1, 6))

