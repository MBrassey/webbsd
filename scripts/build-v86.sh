#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
V86_DIR="$PROJECT_DIR/v86"

echo "=== Building v86 ==="

cd "$V86_DIR"

# Check prerequisites
command -v rustc >/dev/null || { echo "Error: rustc not found"; exit 1; }
command -v clang >/dev/null || { echo "Error: clang not found"; exit 1; }
command -v nasm >/dev/null  || { echo "Error: nasm not found"; exit 1; }
command -v node >/dev/null  || { echo "Error: node not found"; exit 1; }

# Ensure wasm target is available
if ! rustup target list --installed 2>/dev/null | grep -q wasm32-unknown-unknown; then
    echo "Adding wasm32-unknown-unknown target..."
    rustup target add wasm32-unknown-unknown
fi

# Build debug version first (faster, produces debug.html)
echo "Building debug WASM..."
make build/v86-debug.wasm

# Build production version
echo "Building production WASM + JS..."
make build/v86.wasm build/libv86.js

echo "=== v86 build complete ==="
echo "Artifacts:"
ls -lh build/v86.wasm build/libv86.js 2>/dev/null || echo "(check build/ for outputs)"
