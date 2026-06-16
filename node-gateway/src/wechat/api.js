import { logger } from '../logger.js';

function generateUin() {
    const buf = new Uint8Array(4);
    crypto.getRandomValues(buf);
    return Buffer.from(buf).toString('base64');
}

export class WeChatApi {
    constructor(token, baseUrl = 'https://ilinkai.weixin.qq.com') {
        this.token = token;
        this.baseUrl = baseUrl.replace(/\/+$/, '');
        this.uin = generateUin();
        this.nextSendTime = new Map();
    }

    static MIN_SEND_INTERVAL = 2500;

    headers() {
        return {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${this.token}`,
            'AuthorizationType': 'ilink_bot_token',
            'X-WECHAT-UIN': this.uin,
        };
    }

    async request(path, body, timeoutMs = 15_000) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeoutMs);
        const url = `${this.baseUrl}/${path}`;
        logger.debug('API request', { url, body });
        try {
            const res = await fetch(url, {
                method: 'POST',
                headers: this.headers(),
                body: JSON.stringify(body),
                signal: controller.signal,
            });
            if (!res.ok) {
                const text = await res.text();
                throw new Error(`HTTP ${res.status}: ${text}`);
            }
            const json = await res.json();
            logger.debug('API response', json);
            return json;
        } finally {
            clearTimeout(timer);
        }
    }

    async getUpdates(buf) {
        return this.request('ilink/bot/getupdates', buf ? { get_updates_buf: buf } : {}, 35_000);
    }

    async sendMessage(req) {
        const userId = req.msg?.to_user_id;
        if (userId) {
            const now = Date.now();
            const nextAvailable = (this.nextSendTime.get(userId) ?? 0) + WeChatApi.MIN_SEND_INTERVAL;
            const sendAt = Math.max(now, nextAvailable);
            this.nextSendTime.set(userId, sendAt);
            const waitMs = sendAt - now;
            if (waitMs > 0) await new Promise(r => setTimeout(r, waitMs));
        }
        const MAX_RETRIES = 2;
        let delay = 3_000;
        for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
            const res = await this.request('ilink/bot/sendmessage', req);
            if (res.ret === -2) {
                if (userId) this.nextSendTime.set(userId, Date.now() + delay + WeChatApi.MIN_SEND_INTERVAL);
                if (attempt === MAX_RETRIES) {
                    throw new Error(`sendMessage rate-limited after ${MAX_RETRIES} retries`);
                }
                logger.warn('sendMessage rate-limited, retrying', { attempt, delayMs: delay });
                await new Promise(r => setTimeout(r, delay));
                delay = Math.min(delay * 2, 15_000);
                continue;
            }
            return;
        }
    }

    async getConfig(ilinkUserId, contextToken) {
        return this.request('ilink/bot/getconfig', { ilink_user_id: ilinkUserId, context_token: contextToken }, 10_000);
    }

    async sendTyping(req) {
        await this.request('ilink/bot/sendtyping', req, 10_000);
    }

    async getUploadUrl(req) {
        return this.request('ilink/bot/getuploadurl', req);
    }
}
