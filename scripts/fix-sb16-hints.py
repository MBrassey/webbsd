#!/usr/bin/env python3
"""Add SB16 device hints for FreeBSD ISA sound card detection.
Also clean up old ed0 references."""
import subprocess, time, sys, os, socket

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.path.join(BASE, "images", "freebsd.img")
SERIAL_PORT = 45494
MONITOR_PORT = 45495

proc = subprocess.Popen(
    ["qemu-system-i386", "-m", "512",
     "-drive", f"file={IMAGE},format=raw,cache=writethrough",
     "-display", "none",
     "-serial", f"tcp:127.0.0.1:{SERIAL_PORT},server=on,wait=off",
     "-monitor", f"tcp:127.0.0.1:{MONITOR_PORT},server=on,wait=off",
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

def send_cmd(cmd, timeout=30):
    global serial_buf
    marker = f"__OK_{time.time_ns()}__"
    send(cmd + f" && echo {marker}\n", 0.5)
    if not wait_for(marker, timeout):
        print(f"  WARN: No confirm for: {cmd[:70]}...")
        return False
    drain(); return True

print("=== Add SB16 device hints + cleanup ===")
print("Waiting for boot...")
if not wait_for("login:", timeout=300):
    print("ERROR!"); proc.kill(); sys.exit(1)

time.sleep(1)
send("root\n", 3); drain()
send("/bin/sh\n", 1); drain()
send_cmd("service cron stop", timeout=10)

# 1. Add SB16 ISA device hints
# v86 SB16: port 0x220, IRQ 5, DMA 1 (8-bit), DMA 5 (16-bit)
print("\n=== Adding SB16 device hints ===")
send_cmd("grep -q 'hint.sbc.0' /boot/device.hints || echo 'hint.sbc.0.at=\"isa\"' >> /boot/device.hints")
send_cmd("grep -q 'hint.sbc.0.port' /boot/device.hints || echo 'hint.sbc.0.port=\"0x220\"' >> /boot/device.hints")
send_cmd("grep -q 'hint.sbc.0.irq' /boot/device.hints || echo 'hint.sbc.0.irq=\"5\"' >> /boot/device.hints")
send_cmd("grep -q 'hint.sbc.0.drq' /boot/device.hints || echo 'hint.sbc.0.drq=\"1\"' >> /boot/device.hints")
send_cmd("grep -q 'hint.sbc.0.flags' /boot/device.hints || echo 'hint.sbc.0.flags=\"0x15\"' >> /boot/device.hints")

# 2. Clean up old ed0 from rc.conf
print("\n=== Cleaning up ed0 references ===")
send_cmd("sed -i '' '/ifconfig_ed0/d' /etc/rc.conf")

# 3. Remove old ifconfig_DEFAULT that might conflict
# Keep vtnet0 DHCP
serial_buf = b""
send("cat /etc/rc.conf\n", 2)
time.sleep(2)
drain()
print("rc.conf:")
for line in serial_buf.decode(errors="replace").split("\n"):
    s = line.strip()
    if s and not s.startswith("$") and not s.startswith("#"):
        print(f"  {s}")

# Verify device.hints
serial_buf = b""
send("grep sbc /boot/device.hints\n", 2)
time.sleep(2)
drain()
print("\ndevice.hints (sbc):")
for line in serial_buf.decode(errors="replace").split("\n"):
    s = line.strip()
    if s and "sbc" in s and not s.startswith("$"):
        print(f"  {s}")

# Shutdown
print("\nSyncing...")
send("sync\n", 3)
send("sync\n", 3)
send("mount -ur /\n", 2)
send("shutdown -p now\n", 5)
try: proc.wait(timeout=120)
except: proc.kill()
mon.close(); ser.close()
print("Done!")
