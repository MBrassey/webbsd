#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
TINYEMU_DIR="$PROJECT_DIR/TinyEMU"

echo "=== Building TinyEMU (native) ==="

cd "$TINYEMU_DIR"

# Check prerequisites
command -v gcc >/dev/null || command -v cc >/dev/null || { echo "Error: C compiler not found"; exit 1; }

# Build native binary
make clean 2>/dev/null || true
make

echo "=== TinyEMU native build complete ==="
ls -lh temu 2>/dev/null && echo "Binary: $TINYEMU_DIR/temu"

echo ""
echo "=== Building TinyEMU (WASM) ==="

command -v emcc >/dev/null || {
    echo "Warning: emcc not found. Install Emscripten SDK first."
    echo "  git clone https://github.com/emscripten-core/emsdk.git"
    echo "  cd emsdk && ./emsdk install latest && ./emsdk activate latest"
    echo "  source emsdk_env.sh"
    echo "Skipping WASM build."
    exit 0
}

make -f Makefile.js clean 2>/dev/null || true
make -f Makefile.js

echo "=== TinyEMU WASM build complete ==="
ls -lh js/riscvemu64-wasm.js 2>/dev/null
