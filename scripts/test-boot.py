#!/usr/bin/env python3
"""Test: fresh image + serial console with snapshot mode."""

import subprocess, time, socket, sys

IMAGE = "images/freebsd.img"
MP = 45457
SP = 45458

subprocess.run(["pkill", "-9", "-f", "qemu-system-i386"], capture_output=True)
time.sleep(2)

print("Fresh image + serial console + snapshot mode...")
proc = subprocess.Popen([
    "qemu-system-i386", "-m", "512",
    "-drive", f"file={IMAGE},format=raw,snapshot=on",
    "-display", "none",
    "-serial", f"tcp:127.0.0.1:{SP},server=on,wait=off",
    "-monitor", f"tcp:127.0.0.1:{MP},server=on,wait=off",
    "-net", "none", "-no-reboot",
], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

time.sleep(3)
if proc.poll() is not None:
    print(f"QEMU died: {proc.stderr.read().decode()[:300]}")
    sys.exit(1)

mon = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
mon.settimeout(10)
mon.connect(("127.0.0.1", MP))
time.sleep(0.5)
try: mon.recv(4096)
except: pass

def mon_cmd(cmd, delay=0.3):
    mon.send((cmd + "\r\n").encode())
    time.sleep(delay)
    try: return mon.recv(8192).decode(errors='replace')
    except: return ""

def sendkey(key, delay=0.1):
    mon_cmd(f"sendkey {key}", delay)

def type_text(text, delay=0.08):
    km = {' ':'spc','\n':'ret','-':'minus','.':'dot','/':'slash','=':'equal',
          '"':'shift-apostrophe',"'":'apostrophe','\\':'backslash',
          ',':'comma',';':'semicolon',':':'shift-semicolon','_':'shift-minus'}
    for ch in text:
        if ch in km: k = km[ch]
        elif ch.isalpha(): k = f"shift-{ch.lower()}" if ch.isupper() else ch
        elif ch.isdigit(): k = ch
        else: continue
        sendkey(k, delay)

ser = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
ser.settimeout(1)
ser.connect(("127.0.0.1", SP))

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
        except (socket.timeout, BlockingIOError): break

def wait_for(pattern, timeout=180):
    global serial_buf
    start = time.time()
    while time.time() - start < timeout:
        drain()
        if pattern.encode() in serial_buf: return True
        time.sleep(0.3)
    return False

# Wait for beastie menu
time.sleep(5)
# Press 3 to escape to loader prompt
sendkey("3", 0.5)
time.sleep(2)

# Set serial console
type_text('set console="comconsole,vidconsole"\n', 0.05)
time.sleep(0.5)
type_text('set comconsole_speed="115200"\n', 0.05)
time.sleep(0.5)
type_text('set boot_serial="YES"\n', 0.05)
time.sleep(1)

# Boot single-user
print("\n>>> Booting single-user...")
type_text("boot -s\n", 0.05)

# Wait for shell
print("Waiting for shell on serial...")
if wait_for("Enter full pathname of shell", timeout=120):
    print("\n>>> GOT SINGLE-USER PROMPT!")
    ser.send(b"\n")
    time.sleep(3)
    drain()
    print(f"\nSerial total: {len(serial_buf)} bytes")
    print("SUCCESS!")
elif wait_for("#", timeout=30):
    print("\n>>> GOT SHELL PROMPT!")
    print("SUCCESS!")
else:
    print(f"\nFAILED. Serial: {len(serial_buf)} bytes")
    if serial_buf:
        text = serial_buf.decode(errors='replace')
        print(f"Last 500 chars: {text[-500:]}")
    # Take VGA screenshot
    mon_cmd("screendump /tmp/fb13_serial_test.ppm", 2)
    subprocess.run(["magick", "/tmp/fb13_serial_test.ppm", "/tmp/fb13_serial_test.png"],
                   capture_output=True)

proc.kill()
proc.wait()
ser.close()
mon.close()
print("Done")
