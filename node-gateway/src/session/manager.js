import { logger } from '../logger.js';

const SESSION_TTL_MS = 30 * 60 * 1000; // 30 minutes

/**
 * @typedef {Object} UserSession
 * @property {string} userId
 * @property {string} currentPath - e.g. "/试卷/高二"
 * @property {'idle'|'browsing'|'awaiting_download_confirm'} state
 * @property {{fid: string, filename: string}|null} selectedFile
 * @property {number} lastActivity - Date.now()
 */

export function createSessionManager() {
    /** @type {Map<string, UserSession>} */
    const sessions = new Map();

    function get(userId) {
        const s = sessions.get(userId);
        if (!s) return null;
        if (Date.now() - s.lastActivity > SESSION_TTL_MS) {
            sessions.delete(userId);
            return null;
        }
        return s;
    }

    function getOrCreate(userId) {
        let s = get(userId);
        if (!s) {
            s = {
                userId,
                currentPath: '/',
                state: 'browsing',
                selectedFile: null,
                lastActivity: Date.now(),
            };
            sessions.set(userId, s);
        }
        s.lastActivity = Date.now();
        return s;
    }

    function update(userId, partial) {
        const s = getOrCreate(userId);
        Object.assign(s, partial, { lastActivity: Date.now() });
        return s;
    }

    function reset(userId) {
        sessions.delete(userId);
        return getOrCreate(userId);
    }

    // Periodic cleanup
    setInterval(() => {
        const now = Date.now();
        for (const [id, s] of sessions) {
            if (now - s.lastActivity > SESSION_TTL_MS) {
                sessions.delete(id);
                logger.debug('Session expired', { userId: id });
            }
        }
    }, 60_000);

    return { get, getOrCreate, update, reset };
}
