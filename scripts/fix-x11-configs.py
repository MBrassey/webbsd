#!/usr/bin/env python3
"""Write missing X11 system configs to the FreeBSD disk image via QEMU.

Boots multi-user, logs in as root, writes configs, shuts down cleanly.
"""

import subprocess
import time
import sys
import os
import socket

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.path.join(BASE, "images", "freebsd.img")

MONITOR_PORT = 45457
SERIAL_PORT = 45458

print(f"=== Fixing X11 configs in {IMAGE} ===")

proc = subprocess.Popen(
    [
        "qemu-system-i386",
        "-m", "512",
        "-drive", f"file={IMAGE},format=raw,cache=writethrough",
        "-display", "none",
        "-serial", f"tcp:127.0.0.1:{SERIAL_PORT},server=on,wait=off",
        "-monitor", f"tcp:127.0.0.1:{MONITOR_PORT},server=on,wait=off",
        "-net", "none",
        "-no-reboot",
    ],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)

time.sleep(2)

ser = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
ser.settimeout(1)
ser.connect(("127.0.0.1", SERIAL_PORT))

mon = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
mon.settimeout(5)
mon.connect(("127.0.0.1", MONITOR_PORT))
time.sleep(0.5)
try:
    mon.recv(4096)
except:
    pass

serial_buf = b""


def drain():
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


def wait_for(pattern, timeout=180):
    global serial_buf
    start = time.time()
    while time.time() - start < timeout:
        drain()
        if pattern.encode() in serial_buf:
            return True
        time.sleep(0.3)
    return False


def send(text, delay=0.5):
    ser.send(text.encode())
    time.sleep(delay)


def send_cmd(cmd, timeout=30):
    """Send command over serial and wait for prompt."""
    global serial_buf
    # Clear buffer to detect fresh prompt
    marker = f"__OK_{time.time_ns()}__"
    send(cmd + f" && echo {marker}\n", 0.5)
    if not wait_for(marker, timeout):
        print(f"  WARNING: No confirmation for: {cmd[:60]}...")
    drain()


# === Wait for multi-user boot and login ===
print("Waiting for FreeBSD to boot...")
if not wait_for("login:", timeout=300):
    print("ERROR: No login prompt!")
    proc.kill()
    sys.exit(1)

print("\n>>> Logging in as root...")
time.sleep(1)
send("root\n", 3)
drain()

# Switch to /bin/sh (root shell is csh, $() syntax fails in csh)
send("/bin/sh\n", 1)
drain()

# === Write X11 system configs ===
print("\n=== Writing X11 system configs ===")

# 1. VESA driver + Screen config (echo method, never heredocs)
print(">>> Writing 10-vesa.conf...")
send_cmd("mkdir -p /usr/local/etc/X11/xorg.conf.d")

vesa_file = "/usr/local/etc/X11/xorg.conf.d/10-vesa.conf"
vesa_lines = [
    'Section "Device"',
    '    Identifier "Card0"',
    '    Driver "vesa"',
    'EndSection',
    '',
    'Section "Screen"',
    '    Identifier "Screen0"',
    '    Device "Card0"',
    '    DefaultDepth 24',
    '    SubSection "Display"',
    '        Depth 24',
    '        Modes "1920x1080" "1280x1024" "1024x768"',
    '    EndSubSection',
    'EndSection',
]
send(f"echo '{vesa_lines[0]}' > {vesa_file}\n", 0.3)
for line in vesa_lines[1:]:
    send(f"echo '{line}' >> {vesa_file}\n", 0.2)
time.sleep(1)
drain()

# 2. Input + ServerLayout + ServerFlags
print(">>> Writing 20-input.conf...")
input_file = "/usr/local/etc/X11/xorg.conf.d/20-input.conf"
input_lines = [
    'Section "ServerFlags"',
    '    Option "AutoAddDevices" "false"',
    '    Option "AutoEnableDevices" "false"',
    'EndSection',
    '',
    'Section "ServerLayout"',
    '    Identifier "Layout0"',
    '    Screen "Screen0"',
    '    InputDevice "Keyboard0" "CoreKeyboard"',
    '    InputDevice "Mouse0" "CorePointer"',
    'EndSection',
    '',
    'Section "InputDevice"',
    '    Identifier "Keyboard0"',
    '    Driver "kbd"',
    '    Option "XkbLayout" "us"',
    'EndSection',
    '',
    'Section "InputDevice"',
    '    Identifier "Mouse0"',
    '    Driver "mouse"',
    '    Option "Protocol" "auto"',
    '    Option "Device" "/dev/sysmouse"',
    '    Option "ZAxisMapping" "4 5"',
    'EndSection',
]
send(f"echo '{input_lines[0]}' > {input_file}\n", 0.3)
for line in input_lines[1:]:
    send(f"echo '{line}' >> {input_file}\n", 0.2)
time.sleep(1)
drain()

# 3. Xwrapper.config
print(">>> Writing Xwrapper.config...")
send("echo 'allowed_users=anybody' > /usr/local/etc/X11/Xwrapper.config\n", 0.3)
send("echo 'needs_root_rights=yes' >> /usr/local/etc/X11/Xwrapper.config\n", 0.5)
drain()

# 4. xauth stub
print(">>> Creating xauth stub...")
send("echo '#!/bin/sh' > /usr/local/bin/xauth\n", 0.3)
send("echo 'exit 0' >> /usr/local/bin/xauth\n", 0.3)
send("chmod +x /usr/local/bin/xauth\n", 0.5)
drain()

# 5. Ensure moused is enabled
print(">>> Ensuring moused is enabled...")
send_cmd("grep -q moused_enable /etc/rc.conf || echo 'moused_enable=\"YES\"' >> /etc/rc.conf")
send_cmd("grep -q moused_port /etc/rc.conf || echo 'moused_port=\"/dev/psm0\"' >> /etc/rc.conf")

# === Verify ===
print("\n=== Verifying ===")

send("echo '===VESA===' && cat /usr/local/etc/X11/xorg.conf.d/10-vesa.conf\n", 2)
drain()
send("echo '===INPUT===' && cat /usr/local/etc/X11/xorg.conf.d/20-input.conf\n", 2)
drain()
send("echo '===XWRAP===' && cat /usr/local/etc/X11/Xwrapper.config\n", 1)
drain()
send("echo '===XAUTH===' && ls -la /usr/local/bin/xauth\n", 1)
drain()

# Check binaries
send("echo '===BINS==='\n", 0.3)
send("test -x /usr/local/bin/Xorg && echo 'Xorg OK' || echo 'Xorg MISSING'\n", 0.5)
send("test -x /usr/local/bin/i3 && echo 'i3 OK' || echo 'i3 MISSING'\n", 0.5)
send("test -x /usr/local/bin/startx && echo 'startx OK' || echo 'startx MISSING'\n", 0.5)
time.sleep(2)
drain()

# === Shutdown ===
print("\n=== Syncing and shutting down ===")
send("sync\n", 3)
send("sync\n", 3)
send("shutdown -p now\n", 5)

try:
    proc.wait(timeout=60)
except subprocess.TimeoutExpired:
    proc.kill()

mon.close()
ser.close()
print("\n\n=== X11 configs written to disk image! ===")
