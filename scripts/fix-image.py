#!/usr/bin/env python3
"""Fix root password and hostname in the FreeBSD disk image.

Uses QEMU with monitor sendkey to navigate boot menu,
boot single-user, run fsck, mount rw, fix config, shutdown cleanly.
"""

import subprocess
import time
import sys
import os
import socket

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.path.join(BASE, "images", "freebsd.img")

MONITOR_PORT = 45455
SERIAL_PORT = 45456

print(f"Fixing {IMAGE}...")

proc = subprocess.Popen(
    [
        "qemu-system-i386",
        "-m", "512",
        "-drive", f"file={IMAGE},format=raw",
        "-display", "none",
        "-serial", f"tcp:127.0.0.1:{SERIAL_PORT},server=on,wait=off",
        "-monitor", f"tcp:127.0.0.1:{MONITOR_PORT},server=on,wait=off",
        "-net", "none",
        "-no-reboot",
    ],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)

time.sleep(1)

mon = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
mon.settimeout(5)
mon.connect(("127.0.0.1", MONITOR_PORT))
time.sleep(0.5)
try:
    mon.recv(4096)
except:
    pass

def mon_cmd(cmd, delay=0.3):
    mon.send((cmd + "\r\n").encode())
    time.sleep(delay)
    try:
        return mon.recv(8192).decode(errors='replace')
    except:
        return ""

def sendkey(key, delay=0.1):
    mon_cmd(f"sendkey {key}", delay)

def type_text(text, delay=0.08):
    key_map = {
        ' ': 'spc', '\n': 'ret', '-': 'minus', '.': 'dot',
        '/': 'slash', '=': 'equal', '"': 'shift-apostrophe',
        "'": 'apostrophe', '\\': 'backslash', ',': 'comma',
        ';': 'semicolon', ':': 'shift-semicolon', '_': 'shift-minus',
    }
    for ch in text:
        if ch in key_map:
            k = key_map[ch]
        elif ch.isalpha():
            k = f"shift-{ch.lower()}" if ch.isupper() else ch
        elif ch.isdigit():
            k = ch
        else:
            continue
        sendkey(k, delay)

ser = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
ser.settimeout(1)
ser.connect(("127.0.0.1", SERIAL_PORT))

serial_buf = b""
def drain_serial():
    global serial_buf
    while True:
        try:
            data = ser.recv(4096)
            if not data:
                break
            serial_buf += data
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
        except (socket.timeout, BlockingIOError):
            break

def wait_serial(pattern, timeout=180):
    global serial_buf
    start = time.time()
    while time.time() - start < timeout:
        drain_serial()
        if pattern.encode() in serial_buf:
            return True
        time.sleep(0.3)
    return False

def send_serial(text, delay=0.5):
    ser.send(text.encode())
    time.sleep(delay)

# Phase 1: Navigate boot loader menu
print("Waiting 5 seconds for boot loader menu...")
time.sleep(5)

# Press 3 = "Escape to loader prompt"
print(">>> Pressing 3 to escape to loader prompt...")
sendkey("3", 0.5)
time.sleep(2)

# At loader "OK" prompt, set dual console
print(">>> Setting serial console...")
type_text('set console="comconsole,vidconsole"\n', 0.05)
time.sleep(0.5)
type_text('set comconsole_speed="115200"\n', 0.05)
time.sleep(0.5)
type_text('set boot_serial="YES"\n', 0.05)
time.sleep(1)

# Boot single-user
print(">>> Booting single-user...")
type_text("boot -s\n", 0.05)
time.sleep(2)

# Phase 2: Wait for single-user shell on serial
print("\nWaiting for single-user shell on serial...")
if wait_serial("Enter full pathname of shell", timeout=300):
    print("\n>>> Got single-user prompt!")
    send_serial("\n", 3)
elif wait_serial("#", timeout=30):
    print("\n>>> Got shell prompt!")
else:
    drain_serial()
    print(f"\nERROR: No shell. Serial: {len(serial_buf)} bytes")
    proc.kill()
    sys.exit(1)

time.sleep(2)
drain_serial()

# Phase 3: fsck and mount
print("\n=== Running fsck ===")
send_serial("/sbin/fsck -y /dev/ada0p4\n", 2)
# fsck can take a while
if not wait_serial("#", timeout=120):
    print("WARNING: fsck may have timed out")
drain_serial()

print("\n=== Mounting root read-write ===")
send_serial("/sbin/mount -u -o rw /\n", 3)
drain_serial()
send_serial("/sbin/mount -a 2>/dev/null\n", 3)
drain_serial()

# Verify we can write
send_serial("touch /tmp/.write_test && echo WRITE_OK || echo WRITE_FAIL\n", 2)
if not wait_serial("WRITE_OK", timeout=10):
    # Try force mount
    print(">>> Trying force mount...")
    send_serial("/sbin/mount -f -u -o rw /\n", 3)
    drain_serial()

# Phase 4: Fix configuration
print("\n=== Fixing configuration ===")

# Remove root password
print(">>> Removing root password...")
send_serial("sed -i '' 's/^root:[^:]*:/root::/' /etc/master.passwd\n", 1)
send_serial("/usr/sbin/pwd_mkdb -p /etc/master.passwd\n", 3)
drain_serial()

# Fix hostname
print(">>> Setting hostname to 'webbsd'...")
send_serial("sed -i '' 's/hostname=.*/hostname=\"webbsd\"/' /etc/rc.conf\n", 2)
drain_serial()

# loader.conf — configure serial console and fast boot
print(">>> Writing loader.conf...")
send_serial("cat > /boot/loader.conf << 'LOADEREOF'\n", 0.5)
send_serial('autoboot_delay="2"\n', 0.3)
send_serial('beastie_disable="YES"\n', 0.3)
send_serial('console="comconsole,vidconsole"\n', 0.3)
send_serial('comconsole_speed="115200"\n', 0.3)
send_serial('boot_serial="YES"\n', 0.3)
send_serial("LOADEREOF\n", 2)
drain_serial()

# Serial tty
print(">>> Enabling serial tty...")
send_serial("grep -q '^ttyu0' /etc/ttys || printf 'ttyu0\\t\"/usr/libexec/getty std.115200\"\\txterm\\ton\\tsecure\\n' >> /etc/ttys\n", 2)
drain_serial()

# SSH config
print(">>> Configuring SSH...")
send_serial("sed -i '' 's/^#*PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config\n", 1)
send_serial("sed -i '' 's/^#*PermitEmptyPasswords.*/PermitEmptyPasswords yes/' /etc/ssh/sshd_config\n", 1)
drain_serial()

# Ensure DHCP on ed0
send_serial("grep -q ifconfig_ed0 /etc/rc.conf || echo 'ifconfig_ed0=\"DHCP\"' >> /etc/rc.conf\n", 2)
drain_serial()

# Verify
print("\n=== Verifying ===")
send_serial("echo '--- master.passwd root ---' && head -1 /etc/master.passwd\n", 2)
drain_serial()
send_serial("echo '--- rc.conf ---' && cat /etc/rc.conf\n", 2)
drain_serial()
send_serial("echo '--- loader.conf ---' && cat /boot/loader.conf\n", 2)
drain_serial()
send_serial("echo '--- sshd ---' && grep -E 'PermitRoot|PermitEmpty' /etc/ssh/sshd_config | head -5\n", 2)
drain_serial()

# Clean shutdown
print("\n=== Shutting down cleanly ===")
send_serial("sync\n", 2)
send_serial("/sbin/shutdown -p now\n", 5)

try:
    proc.wait(timeout=60)
except subprocess.TimeoutExpired:
    proc.kill()

mon.close()
ser.close()
print("\n\n=== Image fixed successfully! ===")
