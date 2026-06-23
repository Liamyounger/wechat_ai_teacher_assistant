import { createHash, randomBytes } from 'node:crypto';
import { readFileSync, statSync } from 'node:fs';
import { basename, extname } from 'node:path';
import { encryptAesEcb, aesEcbPaddedSize } from './crypto.js';
import { UploadMediaType } from './types.js';
import { CDN_BASE_URL } from '../constants.js';
import { logger } from '../logger.js';

const MAX_FILE_SIZE = 200 * 1024 * 1024;
const IMAGE_EXTS = new Set(['.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.svg', '.ico']);

function isImageFile(fp) { return IMAGE_EXTS.has(extname(fp).toLowerCase()); }

export async function uploadFile(api, toUserId, filePath) {
    const stat = statSync(filePath);
    if (stat.size > MAX_FILE_SIZE) {
        throw new Error(`File too large (${(stat.size / 1024 / 1024).toFixed(1)}MB), max 200MB`);
    }
    const fileName = basename(filePath);
    const isImage = isImageFile(filePath);
    const mediaType = isImage ? UploadMediaType.IMAGE : UploadMediaType.FILE;
    const plaintext = readFileSync(filePath);
    const rawSize = plaintext.length;
    const rawFileMd5 = createHash('md5').update(plaintext).digest('hex');
    const fileSize = aesEcbPaddedSize(rawSize);
    const fileKey = randomBytes(16).toString('hex');
    const aesKey = randomBytes(16);
    const aesKeyHex = aesKey.toString('hex');

    const uploadResp = await api.getUploadUrl({
        filekey: fileKey, media_type: mediaType, to_user_id: toUserId,
        rawsize: rawSize, rawfilemd5: rawFileMd5, filesize: fileSize,
        no_need_thumb: true, aeskey: aesKeyHex,
        base_info: { channel_version: '2.0.0', bot_agent: 'wechat-quark-bot' },
    });
    if (!uploadResp.upload_full_url && !uploadResp.upload_param) {
        throw new Error(`Upload URL error: ${JSON.stringify(uploadResp)}`);
    }

    const encrypted = encryptAesEcb(aesKey, plaintext);
    let uploadUrl = uploadResp.upload_full_url
        || `${CDN_BASE_URL}/upload?encrypted_query_param=${encodeURIComponent(uploadResp.upload_param)}&filekey=${fileKey}`;

    // Timeout scales with file size — 5 min for 200MB
    const uploadTimeout = Math.max(60_000, Math.ceil(rawSize / (200 * 1024 * 1024) * 300_000));
    logger.info('Uploading to CDN', { fileName, encryptedSize: encrypted.length, timeoutMs: uploadTimeout });
    const encryptQueryParam = await uploadToCdn(uploadUrl, encrypted, uploadTimeout);
    return {
        mediaType: isImage ? 'image' : 'file',
        encryptQueryParam, aesKeyHex, fileName, fileSize, rawSize,
    };
}

async function uploadToCdn(url, encrypted, timeoutMs) {
    for (let attempt = 0; attempt < 3; attempt++) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeoutMs);
        try {
            const res = await fetch(url, {
                method: 'POST', body: new Uint8Array(encrypted),
                signal: controller.signal,
                headers: { 'Content-Type': 'application/octet-stream' },
            });
            if (res.status >= 500) { logger.warn('CDN 5xx, retrying', { attempt }); continue; }
            if (!res.ok) {
                const text = await res.text();
                throw new Error(`CDN upload failed: ${res.status} ${text.slice(0, 200)}`);
            }
            const param = res.headers.get('x-encrypted-param');
            if (!param) throw new Error('CDN upload missing x-encrypted-param');
            return param;
        } finally { clearTimeout(timer); }
    }
    throw new Error('CDN upload failed after retries');
}
