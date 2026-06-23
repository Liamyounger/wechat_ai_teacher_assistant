import { clearSyncBuf, loadSyncBuf, saveSyncBuf } from './sync-buf.js';
import { logger } from '../logger.js';

const SESSION_EXPIRED_ERRCODE = -14;

export function createMonitor(api, callbacks) {
    const controller = new AbortController();
    const recentMsgIds = new Set();

    async function run() {
        let failures = 0;
        while (!controller.signal.aborted) {
            try {
                const buf = loadSyncBuf();
                const resp = await api.getUpdates(buf || undefined);
                if (resp.errcode != null && resp.errcode !== 0) {
                    if (resp.errcode === SESSION_EXPIRED_ERRCODE) {
                        logger.error('Session expired — token is no longer valid. Re-run setup.');
                        clearSyncBuf();
                        callbacks.onSessionExpired?.();
                        process.exit(1);
                    }
                    logger.warn('API error response', { errcode: resp.errcode, errmsg: resp.errmsg });
                    await sleep(3_000, controller.signal);
                    continue;
                }
                if (resp.get_updates_buf) saveSyncBuf(resp.get_updates_buf);
                const msgs = resp.msgs ?? [];
                if (msgs.length > 0) {
                    logger.info('Received messages', { count: msgs.length });
                    for (const msg of msgs) {
                        if (msg.message_id && recentMsgIds.has(msg.message_id)) continue;
                        if (msg.message_id) {
                            recentMsgIds.add(msg.message_id);
                            if (recentMsgIds.size > 1000) {
                                const iter = recentMsgIds.values();
                                for (let i = 0; i < 500; i++) recentMsgIds.delete(iter.next().value);
                            }
                        }
                        callbacks.onMessage(msg).catch(err =>
                            logger.error('Error processing message', { error: err.message }));
                    }
                }
                failures = 0;
            } catch (err) {
                if (controller.signal.aborted) break;
                failures++;
                const backoff = failures >= 3 ? 30_000 : 3_000;
                logger.error('Monitor error', { error: err.message, failures });
                await sleep(backoff, controller.signal);
            }
        }
        logger.info('Monitor stopped');
    }

    function stop() { controller.abort(); }
    return { run, stop };
}

function sleep(ms, signal) {
    return new Promise(resolve => {
        if (signal?.aborted) { resolve(); return; }
        const timer = setTimeout(resolve, ms);
        signal?.addEventListener('abort', () => { clearTimeout(timer); resolve(); }, { once: true });
    });
}
