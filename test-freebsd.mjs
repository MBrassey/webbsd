#!/usr/bin/env node
// Test script: boots FreeBSD in v86 headless and checks for login prompt

import path from "node:path";
import fs from "node:fs";
import url from "node:url";
import { V86 } from "./v86/build/libv86.mjs";

const __dirname = url.fileURLToPath(new URL(".", import.meta.url));

const TIMEOUT_MS = 15 * 60 * 1000; // 15 minutes
const IMAGE_PATH = path.join(__dirname, "images/freebsd.img");

if (!fs.existsSync(IMAGE_PATH)) {
    console.error("Error: FreeBSD disk image not found at " + IMAGE_PATH);
    console.error("Run: npm run build:image");
    process.exit(1);
}

const imageSize = fs.statSync(IMAGE_PATH).size;
console.log(`FreeBSD image: ${IMAGE_PATH} (${Math.round(imageSize / 1048576)} MB)`);
console.log("Booting FreeBSD in v86... (this may take 5-15 minutes)");
console.log("Monitoring VGA screen via screen-put-char events...\n");

var booted = false;
var serialOutput = "";

// VGA screen buffer (80x25)
var screenBuffer = new Array(25).fill(null).map(() => new Array(80).fill(" "));

var emulator = new V86({
    wasm_path: path.join(__dirname, "v86/build/v86.wasm"),
    bios: { url: path.join(__dirname, "v86/bios/seabios.bin") },
    vga_bios: { url: path.join(__dirname, "v86/bios/vgabios.bin") },
    hda: { url: IMAGE_PATH, async: true, size: imageSize },
    memory_size: 256 * 1024 * 1024,
    vga_memory_size: 8 * 1024 * 1024,
    autostart: true,
    acpi: true,
});

// Monitor serial output (FreeBSD may or may not use serial console)
emulator.add_listener("serial0-output-byte", function(byte) {
    var chr = String.fromCharCode(byte);
    process.stdout.write(chr);
    serialOutput += chr;
    checkBoot(serialOutput);
});

// Monitor VGA screen via screen-put-char (works in Node.js without screen adapter)
emulator.add_listener("screen-put-char", function(data) {
    var row = data[0];
    var col = data[1];
    var chr = data[2];
    if (row >= 0 && row < 25 && col >= 0 && col < 80) {
        screenBuffer[row][col] = String.fromCharCode(chr || 32);
    }
});

function getScreenText() {
    return screenBuffer.map(row => row.join("")).join("\n");
}

function checkBoot(text) {
    if (booted) return;
    if (text.includes("login:") || text.includes("Login:")) {
        booted = true;
        console.log("\n\n=== SUCCESS: FreeBSD booted to login prompt! ===\n");
        console.log("Full screen:\n" + getScreenText());
        handleLogin();
    }
}

function handleLogin() {
    // Type root + enter via keyboard (VGA console, not serial)
    setTimeout(function() {
        console.log("\nSending 'root' login via keyboard...");
        sendKeys("root\n");
    }, 2000);

    // Run uname after login
    setTimeout(function() {
        sendKeys("uname -a\n");
    }, 5000);

    // Show result and exit
    setTimeout(function() {
        console.log("\nFinal screen:\n" + getScreenText());
        console.log("\n=== Test complete ===");
        emulator.destroy();
        process.exit(0);
    }, 10000);
}

function sendKeys(str) {
    for (var i = 0; i < str.length; i++) {
        var code = str.charCodeAt(i);
        if (str[i] === "\n") {
            emulator.bus.send("keyboard-code", 0x1C);     // Enter key down
            emulator.bus.send("keyboard-code", 0x1C | 0x80); // Enter key up
        } else {
            emulator.keyboard_send_text(str[i]);
        }
    }
}

// Periodically print screen status
var lastScreenSnapshot = "";
var screenPollInterval = setInterval(function() {
    if (booted) {
        clearInterval(screenPollInterval);
        return;
    }
    var text = getScreenText();
    // Only print if screen changed
    var trimmed = text.replace(/\s+/g, " ").trim();
    if (trimmed && trimmed !== lastScreenSnapshot) {
        // Print first few non-empty lines
        var lines = text.split("\n").filter(l => l.trim()).slice(0, 3);
        console.log("[screen] " + lines.map(l => l.trim().substring(0, 80)).join(" | "));
        lastScreenSnapshot = trimmed;
        checkBoot(text);
    }
}, 10000);

// Timeout
setTimeout(function() {
    if (!booted) {
        console.error("\n\n=== TIMEOUT: FreeBSD did not boot within " +
            (TIMEOUT_MS / 60000) + " minutes ===");
        console.error("Final VGA screen:\n" + getScreenText());
        if (serialOutput) {
            console.error("\nSerial output:\n" + serialOutput.slice(-2000));
        }
        emulator.destroy();
        process.exit(1);
    }
}, TIMEOUT_MS);
