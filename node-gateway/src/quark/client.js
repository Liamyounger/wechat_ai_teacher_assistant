import { logger } from '../logger.js';

export class QuarkServiceClient {
    constructor(baseUrl = 'http://127.0.0.1:8000') {
        this.baseUrl = baseUrl.replace(/\/+$/, '');
    }

    async request(path) {
        const url = `${this.baseUrl}${path}`;
        logger.debug('Quark service request', { url });
        const res = await fetch(url, { signal: AbortSignal.timeout(15_000) });
        const body = await res.json();
        if (!res.ok) {
            const err = new Error(body.detail || body.message || `HTTP ${res.status}`);
            err.status = res.status;
            err.body = body;
            throw err;
        }
        return body;
    }

    /** GET /api/v1/folder?path=/试卷/高二 */
    async listFolder(path) {
        return this.request(`/api/v1/folder?path=${encodeURIComponent(path)}`);
    }

    /** GET /api/v1/search?q=keyword&path=/ */
    async searchFiles(query, path = '/') {
        return this.request(
            `/api/v1/search?q=${encodeURIComponent(query)}&path=${encodeURIComponent(path)}`
        );
    }

    /** POST /api/v1/download */
    async submitDownload(fileId, filename) {
        const url = `${this.baseUrl}/api/v1/download`;
        const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ file_id: fileId, filename }),
            signal: AbortSignal.timeout(10_000),
        });
        return res.json();
    }

    /** GET /api/v1/download/{task_id} */
    async getDownloadStatus(taskId) {
        return this.request(`/api/v1/download/${taskId}`);
    }

    /** Poll until download completes or fails. */
    async waitForDownload(taskId, pollMs = 1500, maxWaitMs = 300_000) {
        const start = Date.now();
        while (Date.now() - start < maxWaitMs) {
            const status = await this.getDownloadStatus(taskId);
            if (status.status === 'done') return status;
            if (status.status === 'failed') throw new Error(status.error || 'Download failed');
            await new Promise(r => setTimeout(r, pollMs));
        }
        throw new Error('Download timed out');
    }
}
