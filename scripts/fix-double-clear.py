#!/usr/bin/env python3
"""Fix doubled -C clear in i3 config."""
import subprocess, time, sys, os, socket

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.path.join(BASE, "images", "freebsd.img")
SERIAL_PORT = 45488
MONITOR_PORT = 45489
HOME = "/home/bsduser"
I3CFG = f"{HOME}/.config/i3/config"

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
send_cmd("service cron stop", 10)
send_cmd("killall dhclient 2>/dev/null; true", 5)

# Fix: replace any "fish -C clear -C clear" with "fish -C clear"
send_cmd(f"sed -i '' 's|fish -C clear -C clear|fish -C clear|g' {I3CFG}")
send_cmd(f"chown -R bsduser:bsduser {HOME}/.config")

# Verify
serial_buf = b""
send(f"grep 'fish' {I3CFG}\n", 2)
drain()
for line in serial_buf.decode(errors="replace").split("\n"):
    if "fish" in line and not line.strip().startswith("$"):
        print(f"  {line.strip()}")

send("sync\n", 3)
send("sync\n", 3)
send("mount -ur /\n", 2)
send("shutdown -p now\n", 5)
try: proc.wait(timeout=60)
except: proc.kill()
mon.close(); ser.close()
print("Done!")
