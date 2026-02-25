#!/usr/bin/env node
/**
 * Boot FreeBSD in v86, wait for X11 desktop, save state.
 *
 * Prerequisites: X11 system configs must already be in the disk image
 * (run fix-x11-configs.py first). This script just boots, waits for
 * the desktop to appear, and saves state.
 *
 * Detection: polls VGA graphical_mode property + process checks via serial.
 */

import path from "node:path";
import fs from "node:fs";
import url from "node:url";
import { V86 } from "../v86/build/libv86.mjs";

const __dirname = url.fileURLToPath(new URL(".", import.meta.url));
const BASE = path.join(__dirname, "..");

function loadConfig(configPath) {
    const config = {};
    const content = fs.readFileSync(configPath, "utf-8");
    for (const line of content.split("\n")) {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith("#")) continue;
        const eq = trimmed.indexOf("=");
        if (eq === -1) continue;
        const key = trimmed.slice(0, eq).trim();
        let val = trimmed.slice(eq + 1).trim();
        val = val.replace(/^["']|["']$/g, "");
        config[key] = val;
    }
    return config;
}

const cfg = loadConfig(path.join(BASE, "webbsd.conf"));
const V86_MEMORY = parseInt(cfg.V86_MEMORY || "512");
const V86_VGA_MEMORY = parseInt(cfg.V86_VGA_MEMORY || "32");
const X11_ENABLED = (cfg.X11_ENABLED || "yes") === "yes";

const IMAGE_PATH = path.join(BASE, "images/freebsd.img");
const STATE_PATH = path.join(BASE, "images/freebsd_state.bin");

const imageSize = fs.statSync(IMAGE_PATH).size;
console.log(`Booting FreeBSD to generate saved state...`);
console.log(`Image: ${IMAGE_PATH} (${Math.round(imageSize / 1048576)} MB)`);
console.log(`Memory: ${V86_MEMORY} MB, VGA: ${V86_VGA_MEMORY} MB`);
console.log(`X11: ${X11_ENABLED ? "yes" : "no"}`);

var emulator = new V86({
    wasm_path: path.join(BASE, "v86/build/v86.wasm"),
    bios: { url: path.join(BASE, "v86/bios/seabios.bin") },
    vga_bios: { url: path.join(BASE, "v86/bios/vgabios.bin") },
    hda: { url: IMAGE_PATH, async: true, size: imageSize },
    memory_size: V86_MEMORY * 1024 * 1024,
    vga_memory_size: V86_VGA_MEMORY * 1024 * 1024,
    autostart: true,
    acpi: true,
    net_device: { type: "virtio", relay_url: "fetch" },
});

var serialOutput = "";
var loginDetected = false;
var saving = false;

function checkVgaMode() {
    try {
        return !!emulator.v86.cpu.devices.vga.graphical_mode;
    } catch(e) {
        return false;
    }
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function saveState() {
    if (saving) return;
    saving = true;

    var isGraphical = checkVgaMode();
    console.log(`\nVGA mode at save time: ${isGraphical ? "GRAPHICS" : "TEXT"}`);

    if (X11_ENABLED && !isGraphical) {
        console.log("ERROR: VGA is in text mode. X11 did not start properly.");
        console.log("Run 'python3 scripts/fix-x11-configs.py' to fix the image first.");
        emulator.destroy();
        process.exit(1);
    }

    try {
        console.log("Saving emulator state...");
        var state = await emulator.save_state();
        var buf = Buffer.from(state);
        fs.writeFileSync(STATE_PATH, buf);
        console.log(`State saved: ${STATE_PATH} (${Math.round(buf.length / 1048576)} MB)`);

        const { execSync } = await import("node:child_process");
        try {
            execSync(`zstd -f -9 "${STATE_PATH}" -o "${STATE_PATH}.zst"`);
            var compressedSize = fs.statSync(STATE_PATH + ".zst").size;
            console.log(`Compressed: ${STATE_PATH}.zst (${Math.round(compressedSize / 1048576)} MB)`);
        } catch(e) {
            console.log("zstd not available, skipping compression.");
        }

        console.log("\n=== Done! ===");
        emulator.destroy();
        process.exit(0);
    } catch(e) {
        console.error("Error saving state:", e);
        emulator.destroy();
        process.exit(1);
    }
}

// Serial output — just log it
emulator.add_listener("serial0-output-byte", function(byte) {
    var chr = String.fromCharCode(byte);
    process.stdout.write(chr);
    serialOutput += chr;

    if (serialOutput.length > 500000) {
        serialOutput = serialOutput.slice(-200000);
    }

    // Detect login on serial (means system has booted)
    if (!loginDetected && serialOutput.includes("login:")) {
        loginDetected = true;

        if (!X11_ENABLED) {
            console.log("\n=== FreeBSD booted (text mode). Saving in 5s... ===\n");
            setTimeout(saveState, 5000);
        } else {
            console.log("\n=== FreeBSD booted. Waiting for X11 desktop... ===\n");
            // The auto-login chain should start X automatically:
            // getty → bsduser → .profile → exec startx → Xorg → i3
            // We just need to wait for VGA to switch to graphics mode.
            startPolling();
        }
    }
});

function startPolling() {
    var startTime = Date.now();
    var maxWait = 5 * 60 * 1000; // 5 minutes

    var poll = setInterval(function() {
        var isGraphical = checkVgaMode();
        var elapsed = Math.round((Date.now() - startTime) / 1000);

        if (isGraphical) {
            console.log(`\n=== VGA in GRAPHICS mode after ${elapsed}s ===`);
            console.log("Waiting 55s for layout + delayed clear + wallpaper...\n");
            clearInterval(poll);
            setTimeout(saveState, 55000);
            return;
        }

        if (elapsed % 15 === 0) {
            console.log(`  ${elapsed}s... VGA: text (waiting for graphics)`);
        }

        if (Date.now() - startTime > maxWait) {
            clearInterval(poll);
            console.log(`\nTIMEOUT: VGA never switched to graphics after ${elapsed}s.`);
            console.log("X11 auto-login chain likely failed.");
            console.log("Checking state via serial...\n");

            // Login on serial to debug
            emulator.serial0_send("root\n");
            setTimeout(function() {
                emulator.serial0_send("/bin/sh\n");
            }, 3000);
            setTimeout(function() {
                emulator.serial0_send("echo 'XORG:' $(pgrep -c Xorg 2>/dev/null || echo 0)\n");
                emulator.serial0_send("echo 'I3:' $(pgrep -c i3 2>/dev/null || echo 0)\n");
                emulator.serial0_send("cat /var/log/Xorg.0.log 2>/dev/null | grep -E '(EE|Fatal)' | tail -10\n");
                emulator.serial0_send("cat /home/bsduser/.profile\n");
                emulator.serial0_send("cat /home/bsduser/.xinitrc\n");
                emulator.serial0_send("ls -la /usr/local/etc/X11/xorg.conf.d/\n");
                emulator.serial0_send("ls -la /usr/local/bin/xauth\n");
                emulator.serial0_send("cat /usr/local/etc/X11/Xwrapper.config\n");
            }, 5000);
            setTimeout(function() {
                console.log("\nFailed to capture desktop. Exiting.");
                emulator.destroy();
                process.exit(1);
            }, 15000);
        }
    }, 3000);
}

// Overall safety timeout: 7 minutes
setTimeout(function() {
    if (!saving) {
        console.log("\n\nHARD TIMEOUT: 7 minutes elapsed.");
        emulator.destroy();
        process.exit(1);
    }
}, 7 * 60 * 1000);
