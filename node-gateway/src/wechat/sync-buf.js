import { join } from 'node:path';
import { readFileSync, writeFileSync, unlinkSync, mkdirSync } from 'node:fs';
import { DATA_DIR } from '../constants.js';

const BUF_PATH = join(DATA_DIR, 'get_updates_buf');

export function loadSyncBuf() {
    try { return readFileSync(BUF_PATH, 'utf-8').trim(); }
    catch { return ''; }
}

export function saveSyncBuf(buf) {
    mkdirSync(DATA_DIR, { recursive: true });
    writeFileSync(BUF_PATH, buf, 'utf-8');
}

export function clearSyncBuf() {
    try { unlinkSync(BUF_PATH); } catch { /* ignore */ }
}
