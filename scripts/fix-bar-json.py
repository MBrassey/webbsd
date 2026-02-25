#!/usr/bin/env python3
"""Fix i3bar JSON parsing error + FreeBSD icon for WP button + bar font."""

import subprocess, time, sys, os, socket

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.path.join(BASE, "images", "freebsd.img")

SERIAL_PORT = 45484
MONITOR_PORT = 45485
HOME = "/home/bsduser"
I3CFG = f"{HOME}/.config/i3/config"

# Fixed status.sh: builds entire JSON line as one string (no interleaving),
# no click_events (avoids stdin parsing issues), uses i3 bindsym for actions
# FreeBSD Nerd Font icon: U+F30C = \xEF\x8C\x8C
STATUS_SH_LINES = [
    '#!/bin/sh',
    "S0=$(printf '\\342\\226\\201')",
    "S1=$(printf '\\342\\226\\202')",
    "S2=$(printf '\\342\\226\\203')",
    "S3=$(printf '\\342\\226\\204')",
    "S4=$(printf '\\342\\226\\205')",
    "S5=$(printf '\\342\\226\\206')",
    "S6=$(printf '\\342\\226\\207')",
    "S7=$(printf '\\342\\226\\210')",
    # FreeBSD Nerd Font icon (U+F30C)
    "BSD=$(printf '\\357\\214\\214')",
    '_spark=""',
    'build_spark() {',
    '    _spark=""',
    '    for v in $1; do',
    '        idx=$((v * 7 / 100))',
    '        [ "$idx" -lt 0 ] && idx=0',
    '        [ "$idx" -gt 7 ] && idx=7',
    '        case $idx in',
    '            0) _spark="${_spark}${S0}" ;; 1) _spark="${_spark}${S1}" ;;',
    '            2) _spark="${_spark}${S2}" ;; 3) _spark="${_spark}${S3}" ;;',
    '            4) _spark="${_spark}${S4}" ;; 5) _spark="${_spark}${S5}" ;;',
    '            6) _spark="${_spark}${S6}" ;; *) _spark="${_spark}${S7}" ;;',
    '        esac',
    '    done',
    '}',
    # Simple protocol: version 1, NO click_events (avoids stdin JSON issues)
    'echo \'{"version":1}\'',
    'echo \'[\'',
    'echo \'[]\'',
    'cpu_hist=""; mem_hist=""; cpu_n=0; mem_n=0; prev=""',
    'while true; do',
    '    cp=$(sysctl -n kern.cp_time)',
    '    if [ -n "$prev" ]; then',
    '        set -- $prev; pu=$1; pn=$2; ps=$3; pi=$4; pid=$5',
    '        set -- $cp; cu=$1; cn=$2; cs=$3; ci=$4; cid=$5',
    '        du=$((cu-pu)); dn=$((cn-pn)); ds=$((cs-ps)); di=$((ci-pi)); did=$((cid-pid))',
    '        t=$((du+dn+ds+di+did))',
    '        [ "$t" -gt 0 ] && cpu=$((100*(t-did)/t)) || cpu=0',
    '    else',
    '        cpu=0',
    '    fi',
    '    prev="$cp"',
    '    tp=$(sysctl -n vm.stats.vm.v_page_count)',
    '    fp=$(sysctl -n vm.stats.vm.v_free_count)',
    '    ip=$(sysctl -n vm.stats.vm.v_inactive_count)',
    '    used=$((tp-fp-ip))',
    '    [ "$tp" -gt 0 ] && mem=$((100*used/tp)) || mem=0',
    '    [ "$mem" -lt 0 ] && mem=0; [ "$mem" -gt 100 ] && mem=100',
    '    if [ -z "$cpu_hist" ]; then cpu_hist="$cpu"; else cpu_hist="$cpu_hist $cpu"; fi',
    '    if [ -z "$mem_hist" ]; then mem_hist="$mem"; else mem_hist="$mem_hist $mem"; fi',
    '    cpu_n=$((cpu_n+1)); mem_n=$((mem_n+1))',
    '    [ "$cpu_n" -gt 20 ] && { cpu_hist="${cpu_hist#* }"; cpu_n=20; }',
    '    [ "$mem_n" -gt 20 ] && { mem_hist="${mem_hist#* }"; mem_n=20; }',
    '    build_spark "$cpu_hist"; cpu_spark="$_spark"',
    '    build_spark "$mem_hist"; mem_spark="$_spark"',
    '    [ $cpu -ge 85 ] && cc="#ff3333" || { [ $cpu -ge 60 ] && cc="#ccaa00" || cc="#8899aa"; }',
    '    [ $mem -ge 90 ] && mc="#ff3333" || { [ $mem -ge 70 ] && mc="#ccaa00" || mc="#8899aa"; }',
    '    dt=$(date \'+%a %b %d  %H:%M\')',
    # Build entire JSON line as ONE string to avoid interleaving
    '    line=",["',
    '    line="${line}{\"full_text\":\" >_ \",\"color\":\"#87afd7\",\"separator\":false,\"separator_block_width\":6},"',
    '    line="${line}{\"full_text\":\" www \",\"color\":\"#87afd7\",\"separator\":false,\"separator_block_width\":6},"',
    '    line="${line}{\"full_text\":\" ${BSD} \",\"color\":\"#ab1100\",\"separator\":false,\"separator_block_width\":12},"',
    '    line="${line}{\"full_text\":\" CPU ${cpu_spark} ${cpu}%% \",\"color\":\"${cc}\",\"separator\":false,\"separator_block_width\":18},"',
    '    line="${line}{\"full_text\":\" MEM ${mem_spark} ${mem}%% \",\"color\":\"${mc}\",\"separator\":false,\"separator_block_width\":18},"',
    '    line="${line}{\"full_text\":\" ${dt} \",\"color\":\"#555555\",\"separator\":false}"',
    '    line="${line}]"',
    '    echo "$line"',
    '    sleep 2',
    'done',
]

print("=== Fix i3bar JSON + icon + font ===")

proc = subprocess.Popen(
    [
        "qemu-system-i386",
        "-m", "512",
        "-drive", f"file={IMAGE},format=raw,cache=writethrough",
        "-display", "none",
        "-serial", f"tcp:127.0.0.1:{SERIAL_PORT},server=on,wait=off",
        "-monitor", f"tcp:127.0.0.1:{MONITOR_PORT},server=on,wait=off",
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
    global serial_buf
    marker = f"__OK_{time.time_ns()}__"
    send(cmd + f" && echo {marker}\n", 0.5)
    if not wait_for(marker, timeout):
        print(f"  WARN: No confirm for: {cmd[:70]}...")
        return False
    drain()
    return True

def write_lines(lines, dest_path, executable=False):
    print(f"  Writing {dest_path}...")
    send(f"rm -f {dest_path}\n", 0.3)
    for line in lines:
        escaped = line.replace("'", "'\\''")
        send(f"echo '{escaped}' >> {dest_path}\n", 0.04)
    time.sleep(1)
    drain()
    if executable:
        send_cmd(f"chmod +x {dest_path}")

print("Waiting for boot...")
if not wait_for("login:", timeout=300):
    print("ERROR!")
    proc.kill()
    sys.exit(1)

time.sleep(1)
send("root\n", 3)
drain()
send("/bin/sh\n", 1)
drain()
send_cmd("service cron stop", timeout=10)
send_cmd("killall dhclient 2>/dev/null; true", timeout=5)

# 1. Write fixed status.sh
print("\n=== Writing fixed status.sh ===")
write_lines(STATUS_SH_LINES, f"{HOME}/.config/i3/status.sh", executable=True)

# 2. Update i3bar font to Nerd Font (so FreeBSD icon renders)
print("\n=== Updating i3 bar font ===")
send_cmd(f"sed -i '' 's|font pango:DejaVu Sans Mono 9|font pango:JetBrainsMono Nerd Font Mono, DejaVu Sans Mono 9|' {I3CFG}")

# 3. Add keybindings for toolbar actions (since we removed click_events)
# Check if bindings already exist to avoid duplicates
send_cmd(f"grep -q 'exec netsurf' {I3CFG} || sed -i '' '/bindsym.*Return.*exec/a\\\\bindsym $mod+n exec netsurf' {I3CFG}")
send_cmd(f"grep -q 'cycle-wp' {I3CFG} || sed -i '' '/bindsym.*Return.*exec/a\\\\bindsym $mod+Shift+w exec {HOME}/.config/i3/cycle-wp.sh' {I3CFG}")

# Ownership
send_cmd(f"chown -R bsduser:bsduser {HOME}/.config")

# Verify
print("\n=== Verifying ===")
serial_buf = b""
send(f"head -5 {HOME}/.config/i3/status.sh\n", 2)
send(f"grep 'font pango' {I3CFG}\n", 1)
send(f"grep 'netsurf\\|cycle-wp' {I3CFG}\n", 1)
time.sleep(2)
drain()
for line in serial_buf.decode(errors="replace").split("\n")[-15:]:
    s = line.strip()
    if s and not s.startswith("$") and not s.startswith("#"):
        print(f"  {s}")

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
