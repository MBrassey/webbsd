#!/usr/bin/env node
// Simple dev server with proper MIME types, CORS for v86 WASM, and WISP proxy

import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import url from "node:url";
import { server as wisp, logging } from "@mercuryworkshop/wisp-js/server";

const __dirname = url.fileURLToPath(new URL(".", import.meta.url));
const PORT = process.env.PORT || 8080;

// WISP server config
logging.set_level(logging.DEBUG);

// Prevent unhandled errors from crashing the server
process.on("uncaughtException", (err) => {
    console.error("[uncaughtException]", err.message);
});
process.on("unhandledRejection", (err) => {
    console.error("[unhandledRejection]", err?.message || err);
});

const MIME_TYPES = {
    ".html": "text/html",
    ".js": "application/javascript",
    ".mjs": "application/javascript",
    ".wasm": "application/wasm",
    ".css": "text/css",
    ".json": "application/json",
    ".bin": "application/octet-stream",
    ".img": "application/octet-stream",
    ".iso": "application/octet-stream",
    ".zst": "application/octet-stream",
};

const server = http.createServer((req, res) => {
    const start = Date.now();
    let filePath = path.join(__dirname, decodeURIComponent(url.parse(req.url).pathname));

    // Default to index.html
    if (filePath.endsWith("/")) filePath += "index.html";

    // Security: prevent path traversal
    if (!filePath.startsWith(__dirname)) {
        res.writeHead(403);
        res.end("Forbidden");
        return;
    }

    fs.stat(filePath, (err, stats) => {
        if (err || !stats.isFile()) {
            console.log(`404 ${req.method} ${req.url}`);
            res.writeHead(404);
            res.end("Not found: " + req.url);
            return;
        }
        res.on("finish", () => {
            const ms = Date.now() - start;
            const size = stats.size;
            console.log(`${res.statusCode} ${req.method} ${req.url} ${(size/1048576).toFixed(1)}MB ${ms}ms`);
        });

        const ext = path.extname(filePath).toLowerCase();
        const contentType = MIME_TYPES[ext] || "application/octet-stream";

        // Handle range requests (needed for async disk image loading)
        const range = req.headers.range;
        if (range) {
            const parts = range.replace(/bytes=/, "").split("-");
            const start = parseInt(parts[0], 10);
            const end = parts[1] ? parseInt(parts[1], 10) : stats.size - 1;
            const chunkSize = end - start + 1;

            res.writeHead(206, {
                "Content-Range": `bytes ${start}-${end}/${stats.size}`,
                "Accept-Ranges": "bytes",
                "Content-Length": chunkSize,
                "Content-Type": contentType,
                "Cross-Origin-Opener-Policy": "same-origin",
                "Cross-Origin-Embedder-Policy": "require-corp",
            });
            fs.createReadStream(filePath, { start, end }).pipe(res);
        } else {
            res.writeHead(200, {
                "Content-Length": stats.size,
                "Content-Type": contentType,
                "Cross-Origin-Opener-Policy": "same-origin",
                "Cross-Origin-Embedder-Policy": "require-corp",
            });
            fs.createReadStream(filePath).pipe(res);
        }
    });
});

// WISP proxy: handle WebSocket upgrades for v86 networking
server.on("upgrade", (req, socket, head) => {
    try {
        wisp.routeRequest(req, socket, head);
    } catch(e) {
        console.error("[WISP upgrade error]", e.message);
        socket.destroy();
    }
});

server.listen(PORT, () => {
    console.log(`webBSD dev server running at http://localhost:${PORT}`);
    console.log(`WISP proxy active on ws://localhost:${PORT}/`);
    console.log(`Serving files from ${__dirname}`);
    console.log("Press Ctrl+C to stop.");
});
