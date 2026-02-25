#!/usr/bin/env node
/**
 * Test VM configuration by booting fresh (not from saved state).
 * Verifies: midori installed, status.sh fixed, watchdog as root, networking.
 */
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { V86 } from "./v86/build/libv86.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));

console.log("Booting FreeBSD fresh (no saved state) to test config...");

const emulator = new V86({
    wasm_path: join(__dirname, "v86/build/v86.wasm"),
    memory_size: 3072 * 1024 * 1024,
    vga_memory_size: 64 * 1024 * 1024,
    bios: { url: join(__dirname, "v86/bios/seabios.bin") },
    vga_bios: { url: join(__dirname, "v86/bios/vgabios.bin") },
    hda: {
        url: join(__dirname, "images/freebsd.img"),
        async: true,
        size: 10737418240,
    },
    autostart: true,
    net_device: {
        type: "virtio",
        relay_url: "fetch",
    },
});

let serialBuf = "";
emulator.add_listener("serial0-output-byte", (byte) => {
    const ch = String.fromCharCode(byte);
    serialBuf += ch;
    process.stdout.write(ch);
});

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

function waitFor(pattern, timeout = 180000) {
    return new Promise((resolve) => {
        const start = Date.now();
        const check = setInterval(() => {
            if (serialBuf.includes(pattern)) {
                clearInterval(check);
                resolve(true);
            } else if (Date.now() - start > timeout) {
                clearInterval(check);
                resolve(false);
            }
        }, 500);
    });
}

function send(text) {
    emulator.serial0_send(text);
}

async function sendCmd(cmd) {
    const marker = `__OK_${Date.now()}__`;
    serialBuf = "";
    send(cmd + ` && echo ${marker}\r\n`);
    const ok = await waitFor(marker, 30000);
    await sleep(500);
    return { ok, output: serialBuf };
}

async function runTest() {
    console.log("Waiting for login prompt...\n");
    if (!await waitFor("login:", 300000)) {
        console.log("\nERROR: Never got login prompt");
        emulator.stop();
        process.exit(1);
    }

    await sleep(1000);
    send("root\r\n");
    await sleep(3000);
    send("/bin/sh\r\n");
    await sleep(1000);

    // Stop noisy services
    await sendCmd("service cron stop");
    await sendCmd("killall dhclient 2>/dev/null; true");

    console.log("\n\n========== TESTING ==========\n");

    // Test 1: Midori installed
    const midori = await sendCmd("which midori");
    const midoriOk = midori.output.includes("/usr/local/bin/midori");
    console.log(`\n[1] Midori installed: ${midoriOk ? "PASS" : "FAIL"}`);

    // Test 2: Status.sh has midori (not netsurf)
    const status = await sendCmd("grep -c midori /home/bsduser/.config/i3/status.sh");
    const statusOk = !status.output.includes("0") && status.ok;
    console.log(`[2] Status.sh uses midori: ${statusOk ? "PASS" : "FAIL"}`);

    // Test 3: rc.local exists and starts watchdog
    const rclocal = await sendCmd("cat /etc/rc.local");
    const rclocalOk = rclocal.output.includes("net-watchdog.sh");
    console.log(`[3] rc.local starts watchdog: ${rclocalOk ? "PASS" : "FAIL"}`);

    // Test 4: Watchdog script exists and is root-owned
    const wdog = await sendCmd("ls -la /usr/local/sbin/net-watchdog.sh");
    const wdogOk = wdog.output.includes("root") && wdog.output.includes("net-watchdog");
    console.log(`[4] Watchdog root-owned: ${wdogOk ? "PASS" : "FAIL"}`);

    // Test 5: rc.conf has DHCP
    const rcconf = await sendCmd("grep ifconfig_vtnet0 /etc/rc.conf");
    const dhcpOk = rcconf.output.includes("DHCP");
    console.log(`[5] rc.conf DHCP: ${dhcpOk ? "PASS" : "FAIL"}`);

    // Test 6: DHCP works (fetch backend provides DHCP at 192.168.86.x)
    serialBuf = "";
    send("dhclient vtnet0 2>&1\r\n");
    const dhcpResult = await waitFor("bound to", 30000);
    console.log(`[6] DHCP lease obtained: ${dhcpResult ? "PASS" : "FAIL"}`);

    if (dhcpResult) {
        // Test 7: Can fetch HTTP (fetch backend proxies port 80)
        const httpTest = await sendCmd("fetch -q -o - http://example.com/ 2>&1 | head -3");
        const httpOk = httpTest.output.includes("Example Domain") || httpTest.output.includes("<!doctype") || httpTest.output.includes("<!DOCTYPE");
        console.log(`[7] HTTP fetch works: ${httpOk ? "PASS" : "FAIL"}`);
    }

    // Test 8: i3 config doesn't reference netsurf
    const i3conf = await sendCmd("grep -c netsurf /home/bsduser/.config/i3/config; true");
    const noNetsurf = i3conf.output.includes("\n0\n") || !i3conf.output.match(/[1-9]/);
    console.log(`[8] No netsurf in i3 config: ${noNetsurf ? "PASS" : "FAIL"}`);

    console.log("\n================================");

    const allPass = midoriOk && statusOk && rclocalOk && wdogOk && dhcpOk;
    if (allPass) {
        console.log("All core checks PASSED!");
        console.log("Note: Full relay networking (wss://) requires browser testing.");
    } else {
        console.log("Some checks FAILED - review above.");
    }

    emulator.stop();
    process.exit(allPass ? 0 : 1);
}

runTest();

setTimeout(() => {
    console.log("\nTIMEOUT: 5 minutes elapsed");
    emulator.stop();
    process.exit(1);
}, 300000);
