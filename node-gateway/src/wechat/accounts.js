import { join } from 'node:path';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import process from 'node:process';
import { DATA_DIR } from '../constants.js';
import { saveJson, loadJson } from '../store.js';
import { logger } from '../logger.js';

export const DEFAULT_BASE_URL = 'https://ilinkai.weixin.qq.com';
const ACCOUNTS_DIR = join(DATA_DIR, 'accounts');

export function saveAccount(data) {
    saveJson(join(ACCOUNTS_DIR, `${data.accountId}.json`), data);
    logger.info('Account saved', { accountId: data.accountId });
}

export function loadAccount(accountId) {
    const data = loadJson(join(ACCOUNTS_DIR, `${accountId}.json`), null);
    if (data) {
        logger.info('Account loaded', { accountId });
    }
    return data;
}

/** Load the most recently modified account. Returns null if none exist. */
export function loadLatestAccount() {
    try {
        const files = readdirSync(ACCOUNTS_DIR).filter(f => f.endsWith('.json'));
        if (files.length === 0) return null;
        let latestFile = files[0];
        let latestMtime = 0;
        for (const file of files) {
            const stat = statSync(join(ACCOUNTS_DIR, file));
            if (stat.mtimeMs > latestMtime) {
                latestMtime = stat.mtimeMs;
                latestFile = file;
            }
        }
        return loadAccount(latestFile.replace(/\.json$/, ''));
    } catch {
        return null;
    }
}

export function loadConfig() {
    // Try project-relative path first
    try {
        return JSON.parse(readFileSync(join(process.cwd(), 'config', 'bot.json'), 'utf-8'));
    } catch { /* fall through */ }
    // Then try data dir
    try {
        return JSON.parse(readFileSync(join(DATA_DIR, 'config', 'bot.json'), 'utf-8'));
    } catch { return null; }
}
