#!/usr/bin/env bash
# Install a user-local CoAP runtime; existing compatible Node.js is reused.
set -euo pipefail
actor_root="${1:-$HOME/coap-dataset}"
mkdir -p "$actor_root/runtime"
export PATH="$actor_root:$PATH"
if command -v node >/dev/null 2>&1 && node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 22 ? 0 : 1)'; then
  node_path="$(node -p 'process.execPath')"
else
  for tool in curl tar sha256sum; do
    command -v "$tool" >/dev/null || { printf 'Missing tool: %s. Install with sudo pacman -S --needed curl tar xz\n' "$tool" >&2; exit 1; }
  done
  case "$(uname -m)" in
    x86_64) node_arch=x64 ;;
    aarch64) node_arch=arm64 ;;
    *) printf 'Unsupported CPU architecture\n' >&2; exit 1 ;;
  esac
  cd "$actor_root/runtime"
  curl --fail --location --retry 2 --output SHASUMS256.txt https://nodejs.org/dist/latest-v22.x/SHASUMS256.txt
  archive="$(awk -v suffix="linux-$node_arch.tar.xz" '$2 ~ suffix "$" {print $2}' SHASUMS256.txt)"
  [[ "$archive" =~ ^node-v22\.[0-9]+\.[0-9]+-linux-(x64|arm64)\.tar\.xz$ ]] || { printf 'Unexpected Node archive name\n' >&2; exit 1; }
  curl --fail --location --retry 2 --output "$archive" "https://nodejs.org/dist/latest-v22.x/$archive"
  awk -v file="$archive" '$2 == file {print}' SHASUMS256.txt | sha256sum --check --strict -
  tar -xJf "$archive"
  node_path="$actor_root/runtime/${archive%.tar.xz}/bin/node"
fi
ln -sfn "$node_path" "$actor_root/node"
"$actor_root/node" --version
printf 'Node executable: %s\n' "$actor_root/node"
uname -a
