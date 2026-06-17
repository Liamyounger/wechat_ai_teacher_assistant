import { readFileSync, writeFileSync, chmodSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { logger } from "./logger.js";

export function saveJson(filePath, data) {
    mkdirSync(dirname(filePath), { recursive: true });
    const raw = JSON.stringify(data, null, 2) + "\n";
    writeFileSync(filePath, raw, "utf-8");
    if (process.platform !== 'win32') {
        chmodSync(filePath, 0o600);
    }
}

export function loadJson(filePath, fallback) {
    try {
        const raw = readFileSync(filePath, "utf-8");
        return JSON.parse(raw);
    } catch (err) {
        if (err.code !== 'ENOENT') {
            logger.warn('loadJson failed, using fallback', { filePath, error: err.message });
        }
        return fallback;
    }
}
