#!/usr/bin/env node
// Minimal test: boot FreeBSD ISO in v86 to verify the emulator works

import path from "node:path";
import url from "node:url";
import { V86 } from "./v86/build/libv86.mjs";

const __dirname = url.fileURLToPath(new URL(".", import.meta.url));

console.log("Testing v86 with FreeBSD ISO (CD-ROM boot)...\n");

var emulator = new V86({
    wasm_path: path.join(__dirname, "v86/build/v86.wasm"),
    bios: { url: path.join(__dirname, "v86/bios/seabios-debug.bin") },
    vga_bios: { url: path.join(__dirname, "v86/bios/vgabios-debug.bin") },
    cdrom: { url: path.join(__dirname, "images/FreeBSD-12.4-RELEASE-i386-disc1.iso"), async: true },
    memory_size: 256 * 1024 * 1024,
    autostart: true,
    acpi: true,
});

var screen = new Uint8Array(80 * 25);

emulator.add_listener("serial0-output-byte", function(byte) {
    process.stdout.write(String.fromCharCode(byte));
});

emulator.add_listener("screen-put-char", function(chr) {
    screen[chr[0] + 80 * chr[1]] = chr[2];
});

// Print screen content every 15 seconds
setInterval(function() {
    var lines = [];
    for (var y = 0; y < 25; y++) {
        var line = "";
        for (var x = 0; x < 80; x++) {
            var c = screen[x + 80 * y];
            line += c >= 32 && c < 127 ? String.fromCharCode(c) : " ";
        }
        if (line.trim()) lines.push(line);
    }
    if (lines.length > 0) {
        console.log("\n--- Screen snapshot ---");
        lines.forEach(l => console.log(l));
        console.log("--- End ---\n");
    }
}, 15000);

setTimeout(function() {
    console.log("\n=== 5 minute timeout ===");
    emulator.destroy();
    process.exit(0);
}, 5 * 60 * 1000);
