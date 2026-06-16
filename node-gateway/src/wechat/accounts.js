import { join } from 'node:path';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { DATA_DIR } from '../constants.js';

const ACCOUNTS_DIR = join(DATA_DIR, 'accounts');

export function saveAccount(data) {
    mkdirSync(ACCOUNTS_DIR, { recursive: true });
    writeFileSync(join(ACCOUNTS_DIR, `${data.accountId}.json`), JSON.stringify(data, null, 2));
}

export function loadAccount(accountId) {
    try {
        return JSON.parse(readFileSync(join(ACCOUNTS_DIR, `${accountId}.json`), 'utf-8'));
    } catch { return null; }
}

export function loadConfig() {
    try {
        return JSON.parse(readFileSync(join(DATA_DIR, 'config', 'bot.json'), 'utf-8'));
    } catch { return null; }
}
