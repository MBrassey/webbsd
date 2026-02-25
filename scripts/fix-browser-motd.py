#!/usr/bin/env python3
"""Fix: netsurf binary name (netsurf-gtk3), motd only on left terminal."""
import subprocess, time, sys, os, socket

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.path.join(BASE, "images", "freebsd.img")
SERIAL_PORT = 45494
MONITOR_PORT = 45495
HOME = "/home/bsduser"
I3CFG = f"{HOME}/.config/i3/config"

# Updated status.sh: netsurf-gtk3 instead of netsurf
# Also: new terminals suppress greeting (NO_GREETING=1)
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
    "IBSD=$(printf '\\357\\214\\214')",
    "ITERM=$(printf '\\357\\222\\211')",
    "IWEB=$(printf '\\357\\202\\254')",
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
    '',
    'echo \'{"version":1,"click_events":true}\'',
    'echo \'[\'',
    'echo \'[]\'',
    '',
    '# Output loop in BACKGROUND',
    'cpu_hist=""; mem_hist=""; cpu_n=0; mem_n=0; prev=""',
    '(while true; do',
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
    "    printf ',['",
    '    printf \'{"name":"bsd","full_text":"  %s  ","color":"#ab1100","separator":false,"separator_block_width":8},\' "$IBSD"',
    '    printf \'{"name":"term","full_text":"  %s  ","color":"#87afd7","separator":false,"separator_block_width":8},\' "$ITERM"',
    '    printf \'{"name":"web","full_text":"  %s  ","color":"#87afd7","separator":false,"separator_block_width":14},\' "$IWEB"',
    '    printf \'{"full_text":" CPU %s %d%% ","color":"%s","separator":false,"separator_block_width":18},\' "$cpu_spark" "$cpu" "$cc"',
    '    printf \'{"full_text":" MEM %s %d%% ","color":"%s","separator":false,"separator_block_width":18},\' "$mem_spark" "$mem" "$mc"',
    '    printf \'{"full_text":" %s ","color":"#555555","separator":false}\' "$dt"',
    "    printf ']\\n'",
    '    sleep 2',
    'done) &',
    '',
    '# Click reader in FOREGROUND',
    'while read -r line; do',
    '    case "$line" in',
    '        *\\"bsd\\"*)',
    '            /home/bsduser/.config/i3/cycle-wp.sh >/dev/null 2>&1 &',
    '            ;;',
    '        *\\"term\\"*)',
    '            i3-msg "exec urxvt -e env NO_GREETING=1 fish -C clear" >/dev/null 2>&1 &',
    '            ;;',
    '        *\\"web\\"*)',
    '            i3-msg "exec netsurf-gtk3" >/dev/null 2>&1 &',
    '            ;;',
    '    esac',
    'done',
]

# Golden-3term: Terminal A shows greeting, B+C suppress it
GOLDEN_3TERM_LINES = [
    '#!/bin/sh',
    '# Golden ratio: A(left 62%) | B(top-right 62%) / C(bottom-right 38%)',
    'TERM_CMD="${TERMINAL:-urxvt}"',
    '',
    'sleep 4',
    "i3-msg 'workspace 1'",
    'sleep 1',
    '',
    '# Terminal A (left) - shows greeting',
    '$TERM_CMD -e fish -C "sleep 12; clear" &',
    'sleep 4',
    '',
    "i3-msg 'split horizontal'",
    'sleep 0.5',
    '',
    '# Terminal B (right of A) - no greeting',
    '$TERM_CMD -e env NO_GREETING=1 fish -C "sleep 12; clear" &',
    'sleep 4',
    '',
    "i3-msg 'split vertical'",
    'sleep 0.5',
    '',
    '# Terminal C (below B) - no greeting',
    '$TERM_CMD -e env NO_GREETING=1 fish -C "sleep 12; clear" &',
    'sleep 4',
    '',
    "i3-msg 'focus left'",
    'sleep 0.5',
    "i3-msg 'resize set width 62 ppt'",
    'sleep 0.5',
    '',
    "i3-msg 'focus right'",
    'sleep 0.3',
    "i3-msg 'focus up'",
    'sleep 0.3',
    "i3-msg 'resize set height 62 ppt'",
    'sleep 0.5',
    '',
    "i3-msg 'focus left'",
]

# fish_greeting: only show if NO_GREETING is not set
FISH_GREETING_LINES = [
    'function fish_greeting',
    '    if not set -q NO_GREETING',
    '        set_color red',
    '        echo "Welcome to webBSD"',
    '        set_color normal',
    '    end',
    'end',
]

print("=== Fix browser binary + motd ===")

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
    print("ERROR!"); proc.kill(); sys.exit(1)

time.sleep(1)
send("root\n", 3); drain()
send("/bin/sh\n", 1); drain()
send_cmd("service cron stop", timeout=10)
send_cmd("killall dhclient 2>/dev/null; true", timeout=5)

# 1. Write fixed status.sh (netsurf-gtk3)
print("\n=== Writing status.sh (netsurf-gtk3) ===")
write_lines(STATUS_SH_LINES, f"{HOME}/.config/i3/status.sh", executable=True)

# 2. Write golden-3term.sh (greeting only on terminal A)
print("\n=== Writing golden-3term.sh (greeting on A only) ===")
write_lines(GOLDEN_3TERM_LINES, f"{HOME}/.config/i3/golden-3term.sh", executable=True)

# 3. Write fish_greeting.fish (check NO_GREETING)
print("\n=== Writing fish_greeting.fish ===")
write_lines(FISH_GREETING_LINES, f"{HOME}/.config/fish/functions/fish_greeting.fish")

# 4. Fix i3 config terminal binding to suppress greeting on new terminals
print("\n=== Fixing i3 terminal binding ===")
send_cmd(f"sed -i '' 's|exec urxvt -e fish -C clear|exec urxvt -e env NO_GREETING=1 fish -C clear|' {I3CFG}")
# Also fix any that already have NO_GREETING doubled
send_cmd(f"sed -i '' 's|env NO_GREETING=1 env NO_GREETING=1|env NO_GREETING=1|g' {I3CFG}")

# Ownership
send_cmd(f"chown -R bsduser:bsduser {HOME}/.config")

# Verify
print("\n=== Verifying ===")
serial_buf = b""
send(f"grep netsurf {HOME}/.config/i3/status.sh\n", 1)
send(f"grep NO_GREETING {HOME}/.config/i3/golden-3term.sh | head -2\n", 1)
send(f"cat {HOME}/.config/fish/functions/fish_greeting.fish\n", 1)
send(f"grep 'urxvt' {I3CFG}\n", 1)
time.sleep(3)
drain()
for line in serial_buf.decode(errors="replace").split("\n"):
    s = line.strip()
    if s and not s.startswith("$") and not s.startswith("#"):
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
