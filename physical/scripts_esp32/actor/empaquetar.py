"""Build the portable actor from an explicit file list, without local credentials."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT.parent / "recursos" / "actor_coap_portable.zip"
FILES = {
    "actor_coap.js": "actor_coap.js",
    "actor/plan.js": "actor/plan.js",
    "actor/transport.js": "actor/transport.js",
    "actor/runner.js": "actor/runner.js",
    "actor/ejemplos/piloto_180s.json": "actor/ejemplos/piloto_180s.json",
    "actor/ejemplos/sesion_900s.json": "actor/ejemplos/sesion_900s.json",
    "actor/README.md": "README.md",
    "actor/LEEME_IA.md": "LEEME_IA.md",
    "actor/ficha_sesion.example.json": "actor/ficha_sesion.example.json",
    "servidor/coap.js": "servidor/coap.js",
    "servidor/server.js": "servidor/server.js",
    "tests/actor.test.js": "tests/actor.test.js",
}


def main():
    contents = {target: (ROOT / source).read_bytes() for source, target in FILES.items()}
    inventory = {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}
    contents["PAQUETE_SHA256.json"] = (json.dumps(inventory, indent=2) + "\n").encode()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUTPUT, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(contents.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)
    with zipfile.ZipFile(OUTPUT) as archive:
        assert archive.testzip() is None
        for name, digest in inventory.items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest
    digest = hashlib.sha256(OUTPUT.read_bytes()).hexdigest()
    OUTPUT.with_suffix(".zip.sha256.txt").write_text(f"{digest}  {OUTPUT.name}\n", encoding="utf-8")
    print(f"{OUTPUT}\nSHA256 {digest}")


if __name__ == "__main__":
    main()
