#!/usr/bin/env python3
"""Install the ed (NE2000) driver from FreeBSD kernel.txz distribution,
or compile from source if not available."""
import subprocess, time, sys, os, socket

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.path.join(BASE, "images", "freebsd.img")
SERIAL_PORT = 45494
MONITOR_PORT = 45495

# QEMU with user networking (NAT, em0 gets DHCP automatically)
proc = subprocess.Popen(
    ["qemu-system-i386", "-m", "1024",
     "-drive", f"file={IMAGE},format=raw,cache=writethrough",
     "-display", "none",
     "-serial", f"tcp:127.0.0.1:{SERIAL_PORT},server=on,wait=off",
     "-monitor", f"tcp:127.0.0.1:{MONITOR_PORT},server=on,wait=off",
     "-nic", "user,model=e1000",
     "-no-reboot"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

time.sleep(2)
ser = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
ser.settimeout(1)
ser.connect(("127.0.0.1", SERIAL_PORT))
mon = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
mon.settimeout(5)
mon.connect(("127.0.0.1", MONITOR_PORT))
time.sleep(0.5)
try: mon.recv(4096)
except: pass

serial_buf = b""
def drain():
    global serial_buf
    while True:
        try:
            data = ser.recv(4096)
            if not data: break
            serial_buf += data
        except (socket.timeout, BlockingIOError): break

def wait_for(pattern, timeout=180):
    global serial_buf
    start = time.time()
    while time.time() - start < timeout:
        drain()
        if pattern.encode() in serial_buf: return True
        time.sleep(0.3)
    return False

def send(text, delay=0.5):
    ser.send(text.encode()); time.sleep(delay)

def send_cmd(cmd, timeout=60):
    global serial_buf
    marker = f"__OK_{time.time_ns()}__"
    send(cmd + f" && echo {marker}\n", 0.5)
    if not wait_for(marker, timeout):
        print(f"  WARN: No confirm for: {cmd[:70]}...")
        return False
    drain(); return True

print("=== Install NE2000 (ed) driver ===")
print("Waiting for boot...")
if not wait_for("login:", timeout=300):
    print("ERROR!"); proc.kill(); sys.exit(1)

time.sleep(1)
send("root\n", 3); drain()
send("/bin/sh\n", 1); drain()
send_cmd("service cron stop", timeout=10)

# Wait for em0 to get DHCP
print("Waiting for network (em0 DHCP)...")
send("dhclient em0\n", 10)
drain()

# Test connectivity
serial_buf = b""
send("ifconfig em0 | grep inet\n", 2)
time.sleep(2)
drain()
print("Network:")
for line in serial_buf.decode(errors="replace").split("\n"):
    if "inet" in line and not line.strip().startswith("$"):
        print(f"  {line.strip()}")

# Step 1: Try to get if_ed.ko from kernel.txz distribution
print("\n=== Trying kernel.txz from FreeBSD mirror ===")
send_cmd("mkdir -p /tmp/kmod", 5)
send("fetch -o /tmp/kernel.txz https://download.freebsd.org/releases/i386/13.5-RELEASE/kernel.txz 2>&1\n", 5)
if not wait_for("kernel.txz", timeout=300):
    print("  Download might be slow, waiting longer...")
    wait_for("__", timeout=120)
drain()

# Check if download succeeded and if if_ed.ko is in it
serial_buf = b""
send("ls -la /tmp/kernel.txz 2>&1\n", 2)
send("tar tf /tmp/kernel.txz 2>/dev/null | grep if_ed\n", 5)
time.sleep(3)
drain()
output = serial_buf.decode(errors="replace")
print("Kernel.txz check:")
for line in output.split("\n"):
    s = line.strip()
    if s and ("kernel.txz" in s or "if_ed" in s) and not s.startswith("$"):
        print(f"  {s}")

if "if_ed" in output:
    # Extract just if_ed.ko
    print("\n=== Found if_ed.ko in kernel.txz! Extracting... ===")
    send_cmd("cd / && tar xf /tmp/kernel.txz boot/kernel/if_ed.ko", timeout=60)
    send_cmd("ls -la /boot/kernel/if_ed.ko")
    send_cmd("kldload if_ed 2>&1 && echo ED_LOADED || echo ED_FAILED")
    serial_buf = b""
    send("ifconfig -a 2>&1\n", 3)
    time.sleep(3)
    drain()
    for line in serial_buf.decode(errors="replace").split("\n"):
        s = line.strip()
        if s and not s.startswith("$"):
            print(f"  {s}")
else:
    # Step 2: Compile from source
    print("\n=== if_ed.ko not in kernel.txz, compiling from source ===")
    # Download just the sys source
    send("fetch -o /tmp/src.txz https://download.freebsd.org/releases/i386/13.5-RELEASE/src.txz 2>&1\n", 5)
    print("Downloading source (this takes a while)...")
    if not wait_for("src.txz", timeout=600):
        print("  Still downloading...")
        wait_for("__", timeout=300)
    drain()

    # Extract sys directory
    print("Extracting kernel source...")
    send_cmd("cd / && tar xf /tmp/src.txz usr/src/sys", timeout=120)

    # Build if_ed module
    print("Compiling if_ed module...")
    send_cmd("cd /usr/src/sys/modules/ed && make", timeout=300)
    send_cmd("cd /usr/src/sys/modules/ed && make install", timeout=60)
    send_cmd("ls -la /boot/kernel/if_ed.ko")
    send_cmd("kldload if_ed 2>&1")

    serial_buf = b""
    send("ifconfig -a 2>&1\n", 3)
    time.sleep(3)
    drain()
    for line in serial_buf.decode(errors="replace").split("\n"):
        s = line.strip()
        if s and not s.startswith("$"):
            print(f"  {s}")

# Add to loader.conf
print("\n=== Updating loader.conf ===")
send_cmd("grep -q 'if_ed_load' /boot/loader.conf || echo 'if_ed_load=\"YES\"' >> /boot/loader.conf")
send_cmd("grep -q 'if_ed_load' /boot/loader.conf.local 2>/dev/null || echo 'if_ed_load=\"YES\"' >> /boot/loader.conf.local")

# Clean up temp files
send_cmd("rm -f /tmp/kernel.txz /tmp/src.txz")

# Shutdown
print("\nSyncing...")
send("sync\n", 3)
send("sync\n", 3)
send("mount -ur /\n", 2)
send("shutdown -p now\n", 5)

try:
    proc.wait(timeout=120)
except subprocess.TimeoutExpired:
    proc.kill()

mon.close()
ser.close()
print("Done!")
