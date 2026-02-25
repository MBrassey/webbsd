#!/bin/bash
set -euo pipefail

# Automated FreeBSD installation into a raw disk image using QEMU
# Uses serial console + expect-like automation via QEMU monitor

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
IMAGES_DIR="$PROJECT_DIR/images"
ISO="$IMAGES_DIR/FreeBSD-12.4-RELEASE-i386-disc1.iso"
IMG="$IMAGES_DIR/freebsd.img"
IMG_SIZE="2G"

echo "=== Automated FreeBSD Installation ==="

# Create fresh disk image
rm -f "$IMG"
truncate -s "$IMG_SIZE" "$IMG"
echo "Created $IMG_SIZE disk image: $IMG"

# Create the bsdinstall script
# This automates the entire installation process
cat > "$IMAGES_DIR/installerconfig" << 'INSTALLERCONFIG'
# FreeBSD bsdinstall automated configuration
# This file is read by bsdinstall when placed on the install media

PARTITIONS=auto
DISTRIBUTIONS="kernel.txz base.txz"

#!/bin/sh
# Post-install script

# Set root password to empty
echo "" | pw usermod root -h 0

# Set hostname
sysrc hostname="freebsd"

# Configure network interface (ed0 for NE2000 in v86)
sysrc ifconfig_ed0="DHCP"

# Enable SSH
sysrc sshd_enable="YES"

# Configure serial console
echo 'console="vidconsole"' >> /boot/loader.conf
echo 'autoboot_delay="2"' >> /boot/loader.conf
echo 'beastie_disable="YES"' >> /boot/loader.conf

# Set timezone to UTC
ln -sf /usr/share/zoneinfo/UTC /etc/localtime

# Enable ntpd for time sync
sysrc ntpd_enable="YES"

INSTALLERCONFIG

echo "Created installerconfig"

# We need to inject the installerconfig into the ISO or use an alternative approach
# Since we can't modify the ISO, we'll use QEMU's serial console and send keystrokes

# Alternative approach: Mount the ISO contents and create a custom ISO with installerconfig
# But that requires FreeBSD tools. Instead, let's use a simpler method:
# Extract base.txz and kernel.txz from the ISO and manually set up the filesystem

echo ""
echo "=== Extracting FreeBSD from ISO ==="

WORKDIR=$(mktemp -d)
trap "rm -rf $WORKDIR" EXIT

# Mount ISO
mkdir -p "$WORKDIR/iso"
sudo mount -o loop,ro "$ISO" "$WORKDIR/iso" 2>/dev/null || {
    # Try without sudo
    mkdir -p "$WORKDIR/iso"
    # Use 7z or bsdtar to extract
    if command -v bsdtar >/dev/null 2>&1; then
        echo "Extracting with bsdtar..."
        bsdtar xf "$ISO" -C "$WORKDIR/iso" usr/freebsd-dist/base.txz usr/freebsd-dist/kernel.txz 2>/dev/null || true
    elif command -v 7z >/dev/null 2>&1; then
        echo "Extracting with 7z..."
        7z x -o"$WORKDIR/iso" "$ISO" usr/freebsd-dist/base.txz usr/freebsd-dist/kernel.txz 2>/dev/null || true
    fi
}

# Find the distribution files
BASE_TXZ=""
KERNEL_TXZ=""
for f in "$WORKDIR/iso/usr/freebsd-dist/base.txz" "$WORKDIR/iso/base.txz"; do
    if [ -f "$f" ]; then
        BASE_TXZ="$f"
        break
    fi
done
for f in "$WORKDIR/iso/usr/freebsd-dist/kernel.txz" "$WORKDIR/iso/kernel.txz"; do
    if [ -f "$f" ]; then
        KERNEL_TXZ="$f"
        break
    fi
done

if [ -z "$BASE_TXZ" ] || [ -z "$KERNEL_TXZ" ]; then
    echo "Could not extract FreeBSD distribution files from ISO."
    echo "Trying QEMU serial console approach instead..."

    # Fall back to QEMU headless with expect script
    echo ""
    echo "=== Starting QEMU headless install ==="
    echo "This will boot FreeBSD and automate the installation via serial console."
    echo "It takes about 10-15 minutes..."
    echo ""

    # Use QEMU with monitor pipe for automation
    # The -serial mon:stdio sends serial + monitor to stdout
    # We use the -nographic flag which redirects VGA to serial

    # Create a small helper script that automates the installer
    # FreeBSD installer over serial console
    python3 "$SCRIPT_DIR/qemu-auto-install.py" \
        --iso "$ISO" \
        --img "$IMG" \
        --mem 256

    exit $?
fi

echo "Found base.txz: $BASE_TXZ ($(du -h "$BASE_TXZ" | cut -f1))"
echo "Found kernel.txz: $KERNEL_TXZ ($(du -h "$KERNEL_TXZ" | cut -f1))"

echo ""
echo "=== Setting up disk image ==="

# Create MBR partition table and UFS filesystem
# We need FreeBSD tools for UFS, so use a simpler approach:
# Use QEMU to boot the ISO with a scripted install

echo "Cannot create UFS filesystem without FreeBSD tools."
echo "Using QEMU serial approach..."

python3 "$SCRIPT_DIR/qemu-auto-install.py" \
    --iso "$ISO" \
    --img "$IMG" \
    --mem 256
