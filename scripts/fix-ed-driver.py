#!/usr/bin/env python3
"""Load the ed (NE2000) network driver at boot via loader.conf."""
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
        except: break

def wait_for(p, t=180):
    global serial_buf
    s = time.time()
    while time.time()-s < t:
        drain()
        if p.encode() in serial_buf: return True
        time.sleep(0.3)
    return False

def send(t, d=0.5):
    ser.send(t.encode()); time.sleep(d)

def send_cmd(c, t=30):
    global serial_buf
    m = f"__OK_{time.time_ns()}__"
    send(c + f" && echo {m}\n", 0.5)
    if not wait_for(m, t):
        print(f"  WARN: {c[:60]}")
        return False
    drain(); return True

print("Waiting for boot...")
if not wait_for("login:", 300):
    proc.kill(); sys.exit(1)

time.sleep(1)
send("root\n", 3); drain()
send("/bin/sh\n", 1); drain()

# Check if if_ed.ko exists
serial_buf = b""
send("ls -la /boot/kernel/if_ed.ko 2>&1\n", 2)
send("kldstat 2>&1\n", 2)
send("cat /boot/loader.conf 2>&1\n", 2)
time.sleep(3)
drain()
print("\n=== Current state ===")
for line in serial_buf.decode(errors="replace").split("\n"):
    s = line.strip()
    if s and not s.startswith("$"):
        print(f"  {s}")

# Add if_ed_load to loader.conf
print("\n=== Adding if_ed_load to loader.conf ===")
send_cmd("grep -q 'if_ed_load' /boot/loader.conf || echo 'if_ed_load=\"YES\"' >> /boot/loader.conf")

# Also add to loader.conf.local if it exists
send_cmd("grep -q 'if_ed_load' /boot/loader.conf.local 2>/dev/null || echo 'if_ed_load=\"YES\"' >> /boot/loader.conf.local")

# Verify
serial_buf = b""
send("cat /boot/loader.conf\n", 2)
send("cat /boot/loader.conf.local\n", 2)
time.sleep(2)
drain()
print("\n=== Updated loader.conf ===")
for line in serial_buf.decode(errors="replace").split("\n"):
    s = line.strip()
    if s and not s.startswith("$"):
        print(f"  {s}")

# Shutdown
print("\nSyncing...")
send("sync\n", 3)
send("sync\n", 3)
send("mount -ur /\n", 2)
send("shutdown -p now\n", 5)
try: proc.wait(timeout=60)
except: proc.kill()
mon.close(); ser.close()
print("Done!")
