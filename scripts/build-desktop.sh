#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=============================================="
echo "  webBSD Desktop Builder"
echo "=============================================="
echo ""
echo "This will build a complete FreeBSD desktop image."
echo "Estimated time: 30-60 minutes"
echo ""

# Step 1: Build base image
echo ">>> [1/5] Building base FreeBSD image..."
python3 "$SCRIPT_DIR/build-image.py" "$@"

# Step 2: Fix image config
echo ""
echo ">>> [2/5] Configuring image (hostname, root, SSH, serial)..."
python3 "$SCRIPT_DIR/fix-image.py"

# Step 3: Network config
echo ""
echo ">>> [3/5] Configuring networking (DNS, auto-DHCP)..."
python3 "$SCRIPT_DIR/fix-network.py"

# Step 4: Install X11 desktop
echo ""
echo ">>> [4/5] Installing X11 desktop environment..."
python3 "$SCRIPT_DIR/install-x11.py"

# Step 5: Generate saved state
echo ""
echo ">>> [5/5] Generating saved state for instant boot..."
node "$SCRIPT_DIR/save-state.mjs"

echo ""
echo "=============================================="
echo "  webBSD desktop build complete!"
echo "=============================================="
echo ""
echo "Start the dev server:"
echo "  npm run dev"
echo ""
echo "Then open http://localhost:8080"
