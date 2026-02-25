#!/usr/bin/env node
/**
 * Boot in v86 with net_device, check PCI and ed driver status.
 */
import path from "node:path";
import fs from "node:fs";
import url from "node:url";
import { V86 } from "../v86/build/libv86.mjs";

const __dirname = url.fileURLToPath(new URL(".", import.meta.url));
const BASE = path.join(__dirname, "..");
const IMAGE_PATH = path.join(BASE, "images/freebsd.img");
const imageSize = fs.statSync(IMAGE_PATH).size;

var emulator = new V86({
    wasm_path: path.join(BASE, "v86/build/v86.wasm"),
    bios: { url: path.join(BASE, "v86/bios/seabios.bin") },
    vga_bios: { url: path.join(BASE, "v86/bios/vgabios.bin") },
    hda: { url: IMAGE_PATH, async: true, size: imageSize },
    memory_size: 512 * 1024 * 1024,
    vga_memory_size: 8 * 1024 * 1024,
    autostart: true,
    acpi: true,
    net_device: { type: "ne2k" },
});

var serialOutput = "";
var loginSeen = false;
var cmdsSent = false;

emulator.add_listener("serial0-output-byte", function(byte) {
    var chr = String.fromCharCode(byte);
    process.stdout.write(chr);
    serialOutput += chr;

    if (!loginSeen && serialOutput.includes("login:")) {
        loginSeen = true;
        console.log("\n=== Login detected, sending debug commands ===\n");
        setTimeout(sendCommands, 2000);
    }
});

function sendCommands() {
    if (cmdsSent) return;
    cmdsSent = true;

    emulator.serial0_send("root\n");
    setTimeout(() => {
        emulator.serial0_send("/bin/sh\n");
    }, 3000);
    setTimeout(() => {
        emulator.serial0_send("echo '=== PCICONF ==='\n");
        emulator.serial0_send("pciconf -lv 2>&1\n");
    }, 5000);
    setTimeout(() => {
        emulator.serial0_send("echo '=== IFCONFIG ==='\n");
        emulator.serial0_send("ifconfig -a 2>&1\n");
    }, 8000);
    setTimeout(() => {
        emulator.serial0_send("echo '=== DMESG ED ==='\n");
        emulator.serial0_send("dmesg | grep -i 'ed0\\|ed1\\|ne2k\\|rtl8029\\|8029\\|10ec\\|device 5' 2>&1\n");
    }, 10000);
    setTimeout(() => {
        emulator.serial0_send("echo '=== KERNEL CONF ==='\n");
        emulator.serial0_send("sysctl kern.conftxt 2>/dev/null | grep 'device.*ed' || echo 'no conftxt'\n");
    }, 12000);
    setTimeout(() => {
        emulator.serial0_send("echo '=== DEVINFO ==='\n");
        emulator.serial0_send("devinfo -rv 2>&1 | grep -A2 'ed\\|ne2k\\|pci0:0:5' | head -20\n");
    }, 14000);
    setTimeout(() => {
        emulator.serial0_send("echo '=== TRY KLDLOAD ==='\n");
        emulator.serial0_send("kldload if_ed 2>&1; kldload miibus 2>&1; ifconfig -a 2>&1\n");
    }, 16000);
    setTimeout(() => {
        console.log("\n\n=== DONE ===");
        emulator.destroy();
        process.exit(0);
    }, 25000);
}

setTimeout(() => {
    console.log("\nHARD TIMEOUT");
    emulator.destroy();
    process.exit(1);
}, 5 * 60 * 1000);
