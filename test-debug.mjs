#!/usr/bin/env node
// Quick debug test: boot FreeBSD with debug BIOS and serial output

import path from "node:path";
import fs from "node:fs";
import url from "node:url";
import { V86 } from "./v86/build/libv86.mjs";

const __dirname = url.fileURLToPath(new URL(".", import.meta.url));
const IMAGE_PATH = path.join(__dirname, "images/freebsd.img");
const imageSize = fs.statSync(IMAGE_PATH).size;

console.log(`Image: ${IMAGE_PATH} (${Math.round(imageSize / 1048576)} MB)`);
console.log("Starting v86 with debug BIOS...\n");

var emulator = new V86({
    wasm_path: path.join(__dirname, "v86/build/v86.wasm"),
    bios: { url: path.join(__dirname, "v86/bios/seabios-debug.bin") },
    vga_bios: { url: path.join(__dirname, "v86/bios/vgabios-debug.bin") },
    hda: { url: IMAGE_PATH, async: true, size: imageSize },
    memory_size: 256 * 1024 * 1024,
    vga_memory_size: 8 * 1024 * 1024,
    autostart: true,
    acpi: true,
    log_level: 0,
});

// Serial output (debug BIOS sends output here)
emulator.add_listener("serial0-output-byte", function(byte) {
    process.stdout.write(String.fromCharCode(byte));
});

// Timeout after 3 minutes
setTimeout(function() {
    console.log("\n\n=== 3 minute timeout ===");
    emulator.destroy();
    process.exit(1);
}, 3 * 60 * 1000);
