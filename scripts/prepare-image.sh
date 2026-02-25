#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
IMAGES_DIR="$PROJECT_DIR/images"
ISO_NAME="FreeBSD-12.4-RELEASE-i386-disc1.iso"
ISO_URL="http://ftp-archive.freebsd.org/pub/FreeBSD-Archive/old-releases/i386/ISO-IMAGES/12.4/$ISO_NAME"
IMG_NAME="freebsd.img"
IMG_SIZE="2G"

mkdir -p "$IMAGES_DIR"
cd "$IMAGES_DIR"

# Step 1: Download ISO if not present
if [ ! -f "$ISO_NAME" ]; then
    echo "=== Downloading FreeBSD 12.4 i386 ISO ==="
    echo "URL: $ISO_URL"
    curl -L -o "$ISO_NAME.part" "$ISO_URL"
    mv "$ISO_NAME.part" "$ISO_NAME"
    echo "Download complete: $(du -h "$ISO_NAME" | cut -f1)"
else
    echo "ISO already exists: $ISO_NAME"
fi

# Step 2: Create raw disk image
if [ ! -f "$IMG_NAME" ]; then
    echo "=== Creating $IMG_SIZE raw disk image ==="
    qemu-img create -f raw "$IMG_NAME" "$IMG_SIZE"
else
    echo "Disk image already exists: $IMG_NAME ($(du -h "$IMG_NAME" | cut -f1))"
fi

echo ""
echo "=== Ready for FreeBSD installation ==="
echo ""
echo "Run the following command to install FreeBSD interactively:"
echo ""
echo "  qemu-system-i386 \\"
echo "    -m 256 \\"
echo "    -cdrom $IMAGES_DIR/$ISO_NAME \\"
echo "    -hda $IMAGES_DIR/$IMG_NAME \\"
echo "    -boot d \\"
echo "    -net nic,model=ne2k_pci \\"
echo "    -net user \\"
echo "    -display sdl"
echo ""
echo "Installation tips for v86 compatibility:"
echo "  - Choose a minimal install (no ports, games, or docs)"
echo "  - Set root password to empty or 'root' for easy demo access"
echo "  - Configure the NE2000 NIC as ed0"
echo "  - Use Auto (UFS) partitioning"
echo "  - After install, configure /boot/loader.conf:"
echo '    autoboot_delay="0"'
echo '    beastie_disable="YES"'
echo '    console="vidconsole"'
echo ""
echo "After installation, the image at $IMAGES_DIR/$IMG_NAME is ready for v86."
