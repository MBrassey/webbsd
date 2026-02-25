#!/usr/bin/env python3
"""Fix golden-3term.sh Terminal C to run tty-clock instead of fish."""
import subprocess, time, sys, os, socket

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.path.join(BASE, "images", "freebsd.img")
SERIAL_PORT = 45494
MONITOR_PORT = 45495
HOME = "/home/bsduser"

proc = subprocess.Popen(
    ["qemu-system-i386", "-m", "1024",
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

def send_cmd(cmd, timeout=60):
    global serial_buf
    marker = f"__OK_{time.time_ns()}__"
    send(cmd + f" && echo {marker}\n", 0.5)
    if not wait_for(marker, timeout):
        print(f"  WARN: No confirm for: {cmd[:70]}...")
        return False
    drain(); return True

print("=== Fix Terminal C to tty-clock ===")
print("Waiting for boot...")
if not wait_for("login:", timeout=300):
    print("ERROR!"); proc.kill(); sys.exit(1)

time.sleep(1)
send("root\n", 3); drain()
send("/bin/sh\n", 1); drain()
send_cmd("service cron stop", timeout=10)

SCRIPT = f"{HOME}/.config/i3/golden-3term.sh"

# Find the line with "Terminal C"
serial_buf = b""
send(f"grep -n 'Terminal C\\|TERM_CMD' {SCRIPT}\n", 2)
time.sleep(2); drain()
print("Matching lines:")
print(serial_buf.decode(errors="replace")[:500])

# The Terminal C comment is followed by the $TERM_CMD line we need to change.
# Use sed: find "Terminal C" line, then on the next line replace
print("\n=== Replacing Terminal C command ===")
# Replace the $TERM_CMD line after "Terminal C" comment
send_cmd(f"sed -i '' '/Terminal C/{{n; s|.*TERM_CMD.*|$TERM_CMD -e tty-clock -c -C 1 -t \\&|; }}' {SCRIPT}")

# Verify
print("\n=== Updated script ===")
serial_buf = b""
send(f"cat {SCRIPT}\n", 2)
time.sleep(3); drain()
result = serial_buf.decode(errors="replace")
for line in result.split("\n"):
    s = line.strip()
    if s and not s.startswith("$") and not s.startswith("cat "):
        print(f"  {s}")

if "tty-clock" in result:
    print("\nClock in Terminal C!")
else:
    print("\nERROR: tty-clock not found")

send_cmd(f"chown -R bsduser:bsduser {HOME}")

print("\nSyncing...")
send("sync\n", 3)
send("sync\n", 3)
send("mount -ur /\n", 2)
send("shutdown -p now\n", 5)
try: proc.wait(timeout=120)
except: proc.kill()
mon.close(); ser.close()
print("Done!")
