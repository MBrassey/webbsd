#!/usr/bin/env python3
"""Make the third terminal (bottom-left) auto-run tty-clock."""
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

print("=== Fix T3 to run tty-clock ===")
print("Waiting for boot...")
if not wait_for("login:", timeout=300):
    print("ERROR!"); proc.kill(); sys.exit(1)

time.sleep(1)
send("root\n", 3); drain()
send("/bin/sh\n", 1); drain()
send_cmd("service cron stop", timeout=10)

# Show current startup.sh
print("\n=== Current startup.sh ===")
serial_buf = b""
send(f"cat {HOME}/.config/i3/startup.sh\n", 2)
time.sleep(3); drain()
print(serial_buf.decode(errors="replace")[:800])

# The third urxvt exec (T3, bottom-left) needs to run clock
# Pattern: the third "i3-msg 'exec urxvt" line
# Replace: i3-msg 'exec urxvt -e fish' (3rd occurrence) -> i3-msg 'exec urxvt -e fish -c "tty-clock -c -C 1 -t"'
#
# Use awk to replace only the 3rd occurrence of the urxvt exec line
print("\n=== Replacing T3 terminal with clock ===")
send_cmd(f"cp {HOME}/.config/i3/startup.sh {HOME}/.config/i3/startup.sh.bak")

# Use awk: on the 3rd match of 'exec urxvt', replace with clock version
awk_cmd = f"""awk '/exec urxvt/{{n++; if(n==3){{sub(/exec urxvt -e fish/, "exec urxvt -e fish -c \\x27tty-clock -c -C 1 -t\\x27")}}}}1' {HOME}/.config/i3/startup.sh.bak > {HOME}/.config/i3/startup.sh"""
send_cmd(awk_cmd, timeout=30)

# Verify
print("\n=== Updated startup.sh ===")
serial_buf = b""
send(f"cat {HOME}/.config/i3/startup.sh\n", 2)
time.sleep(3); drain()
result = serial_buf.decode(errors="replace")
print(result[:800])

# Check that we have the clock line
if "tty-clock" in result:
    print("\nClock terminal configured!")
else:
    print("\nWARN: tty-clock not found, trying manual fix...")
    # Fallback: use sed to replace the 3rd urxvt line
    # Find line number of 3rd urxvt exec
    serial_buf = b""
    send(f"grep -n 'exec urxvt' {HOME}/.config/i3/startup.sh.bak\n", 2)
    time.sleep(2); drain()
    lines_out = serial_buf.decode(errors="replace")
    print(f"urxvt lines: {lines_out}")

    # Parse the 3rd line number
    matches = []
    for line in lines_out.split("\n"):
        if "exec urxvt" in line and line[0].isdigit():
            matches.append(line.split(":")[0])

    if len(matches) >= 3:
        line_num = matches[2]
        print(f"Replacing line {line_num}")
        send_cmd(f"sed -i '' '{line_num}s|exec urxvt -e fish|exec urxvt -e fish -c \"tty-clock -c -C 1 -t\"|' {HOME}/.config/i3/startup.sh")

        serial_buf = b""
        send(f"grep tty-clock {HOME}/.config/i3/startup.sh\n", 2)
        time.sleep(2); drain()
        print(f"Verify: {serial_buf.decode(errors='replace')}")

send_cmd(f"rm -f {HOME}/.config/i3/startup.sh.bak")
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
