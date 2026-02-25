#!/usr/bin/env python3
"""Diagnose why X11 isn't starting on ttyv0.
Boot QEMU, log in on serial, check processes and try startx manually.
"""

import subprocess, time, sys, os, socket

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.path.join(BASE, "images", "freebsd.img")

proc = subprocess.Popen(
    ["qemu-system-i386", "-m", "512",
     "-drive", f"file={IMAGE},format=raw",
     "-display", "none",
     "-serial", "tcp:127.0.0.1:45456,server=on,wait=off",
     "-no-reboot"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
time.sleep(1)

ser = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
ser.settimeout(1)
ser.connect(("127.0.0.1", 45456))

serial_buf = b""

def drain():
    global serial_buf
    while True:
        try:
            data = ser.recv(4096)
            if not data: break
            serial_buf += data
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
        except: break

def wait_for(pattern, timeout=300):
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

print("Waiting for boot...")
if not wait_for("login:"):
    print("ERROR: No login prompt")
    proc.kill()
    sys.exit(1)

print("\n>>> Logging in...")
send("root\n", 5)
drain()

print("\n=== DIAGNOSTICS ===")

# Check what's running on ttyv0
print("\n--- Processes on ttyv* ---")
send("ps aux | grep ttyv\n", 3)
drain()

# Check getty processes
print("\n--- Getty processes ---")
send("ps aux | grep getty\n", 3)
drain()

# Check if bsduser is logged in anywhere
print("\n--- Who is logged in ---")
send("who\n", 2)
drain()

# Check bsduser's shell and home
print("\n--- bsduser entry ---")
send("grep bsduser /etc/passwd\n", 2)
drain()

# Check bsduser's password in master.passwd
print("\n--- bsduser password ---")
send("grep bsduser /etc/master.passwd\n", 2)
drain()

# Check ttys
print("\n--- ttyv0 in ttys ---")
send("grep ttyv0 /etc/ttys\n", 2)
drain()

# Check gettytab
print("\n--- gettytab Al entry ---")
send("grep -A2 'Autologin' /etc/gettytab\n", 2)
drain()

# Check if .profile exists and has startx
print("\n--- .profile ---")
send("cat /home/bsduser/.profile\n", 2)
drain()

# Check if .xinitrc exists
print("\n--- .xinitrc ---")
send("cat /home/bsduser/.xinitrc\n", 2)
drain()

# Check if i3 config exists
print("\n--- i3 config exists ---")
send("ls -la /home/bsduser/.config/i3/config\n", 2)
drain()

# Check Xorg log for errors
print("\n--- Xorg log (last 20 lines) ---")
send("tail -20 /var/log/Xorg.0.log 2>/dev/null || echo 'NO XORG LOG'\n", 3)
drain()

# Try to manually start X as bsduser (in background)
print("\n--- Trying manual startx as bsduser ---")
send("su - bsduser -c 'startx' &\n", 10)
drain()

# Wait and check if x11_ready appeared
time.sleep(15)
send("ls -la /tmp/x11_ready 2>&1\n", 2)
drain()
send("cat /tmp/x11_ready 2>&1\n", 2)
drain()

# Check Xorg log after attempt
print("\n--- Xorg log after attempt ---")
send("tail -30 /var/log/Xorg.0.log 2>/dev/null || echo 'NO XORG LOG'\n", 3)
drain()

# Also check bsduser's home Xorg log
send("tail -30 /home/bsduser/.local/share/xorg/Xorg.0.log 2>/dev/null || echo 'NO USER XORG LOG'\n", 3)
drain()

# Shutdown
print("\n=== Shutting down ===")
send("sync\n", 1)
send("shutdown -p now\n", 5)

try:
    proc.wait(timeout=60)
except subprocess.TimeoutExpired:
    proc.kill()

ser.close()
print("\n=== Diagnostics complete ===")
