import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { homedir } from 'node:os';
import { MessageItemType, MessageType, MessageState, TypingStatus } from './types.js';
import { uploadFile } from './upload.js';
import { logger } from '../logger.js';

export function createSender(api, botAccountId) {
    let counter = 0;
    const ticketCache = new Map();

    function genClientId() { return `wqb-${Date.now()}-${++counter}`; }

    async function getTypingTicket(userId, contextToken) {
        const cached = ticketCache.get(userId);
        if (cached && Date.now() - cached.at < 24 * 60 * 60 * 1000) return cached.ticket;
        try {
            const resp = await api.getConfig(userId, contextToken);
            if (resp.ret === 0 && resp.typing_ticket) {
                ticketCache.set(userId, { ticket: resp.typing_ticket, at: Date.now() });
                return resp.typing_ticket;
            }
        } catch (err) { logger.warn('getConfig failed', { err: err.message }); }
        return '';
    }

    function startTyping(toUserId, contextToken) {
        let cancelled = false;
        (async () => {
            const ticket = await getTypingTicket(toUserId, contextToken);
            if (!ticket || cancelled) return;
            try { await api.sendTyping({ ilink_user_id: toUserId, typing_ticket: ticket, status: TypingStatus.TYPING }); }
            catch { return; }
            while (!cancelled) {
                await new Promise(r => setTimeout(r, 5_000));
                if (cancelled) break;
                try { await api.sendTyping({ ilink_user_id: toUserId, typing_ticket: ticket, status: TypingStatus.TYPING }); }
                catch { break; }
            }
            try { await api.sendTyping({ ilink_user_id: toUserId, typing_ticket: ticket, status: TypingStatus.CANCEL }); }
            catch { /* ignore */ }
        })();
        return () => { cancelled = true; };
    }

    async function sendText(toUserId, contextToken, text) {
        const clientId = genClientId();
        const msg = {
            from_user_id: botAccountId,
            to_user_id: toUserId,
            client_id: clientId,
            message_type: MessageType.BOT,
            message_state: MessageState.FINISH,
            context_token: contextToken,
            item_list: [{ type: MessageItemType.TEXT, text_item: { text } }],
        };
        await api.sendMessage({ msg });
    }

    async function sendFile(toUserId, contextToken, filePath) {
        const resolved = resolve(filePath.replace(/^~/, homedir()));
        if (!existsSync(resolved)) {
            await sendText(toUserId, contextToken, `文件不存在: ${resolved}`);
            return;
        }
        let media;
        try {
            media = await uploadFile(api, toUserId, resolved);
        } catch (err) {
            if (err.message.includes('File too large')) {
                await sendText(toUserId, contextToken, `⚠️ ${err.message}\n建议用电脑夸克 App 直接下载。`);
            } else {
                await sendText(toUserId, contextToken, `上传失败: ${err.message}`);
            }
            return;
        }
        const aesKeyBase64 = Buffer.from(media.aesKeyHex).toString('base64');
        const item = media.mediaType === 'image' ? {
            type: MessageItemType.IMAGE,
            image_item: {
                media: { encrypt_query_param: media.encryptQueryParam, aes_key: aesKeyBase64, encrypt_type: 1 },
                mid_size: media.fileSize,
            },
        } : {
            type: MessageItemType.FILE,
            file_item: {
                media: { encrypt_query_param: media.encryptQueryParam, aes_key: aesKeyBase64, encrypt_type: 1 },
                file_name: media.fileName,
                len: String(media.rawSize),
            },
        };
        const msg = {
            from_user_id: botAccountId,
            to_user_id: toUserId,
            client_id: genClientId(),
            message_type: MessageType.BOT,
            message_state: MessageState.FINISH,
            context_token: contextToken,
            item_list: [item],
        };
        await api.sendMessage({ msg });
    }

    return { sendText, startTyping, sendFile };
}
