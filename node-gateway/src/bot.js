import { MessageType } from './wechat/types.js';
import { renderMenu } from './menu/renderer.js';
import { routeInput } from './menu/router.js';
import { logger } from './logger.js';

/**
 * Create the message handler. Returns a function that processes one WeChat message.
 */
export function createHandler(sessionManager, quarkClient, sender) {

    return async function handleMessage(msg, contextToken) {
        if (msg.message_type !== MessageType.USER) return;
        if (!msg.from_user_id || !msg.item_list) return;

        const userId = msg.from_user_id;
        const text = extractText(msg.item_list);
        const session = sessionManager.getOrCreate(userId);

        // Handle search results selection (numbered choice while in search state)
        if (session.state === 'search_results') {
            const num = parseInt(text.trim(), 10);
            if (!isNaN(num) && num >= 1 && session.searchResults &&
                num <= session.searchResults.length) {
                const selected = session.searchResults[num - 1];
                if (selected.is_dir) {
                    session.currentPath = selected.path;
                    session._page = 0;
                    session.state = 'browsing';
                    session.searchResults = null;
                    await showCurrentFolder(userId, contextToken, session, quarkClient, sender);
                } else {
                    session.selectedFile = { fid: selected.fid, filename: selected.name };
                    session.state = 'awaiting_download_confirm';
                    session.searchResults = null;
                    await sender.sendText(userId, contextToken,
                        `确认下载 「${selected.name}」？\n回复 y 确认，其他键取消`);
                }
                return;
            }
            // Any other input exits search mode
            session.state = 'browsing';
            session.searchResults = null;
        }
        if (session.state === 'awaiting_download_confirm') {
            if (text.toLowerCase() === 'y' || text === '是' || text === '确认') {
                await handleDownload(userId, contextToken, session, quarkClient, sender);
            } else {
                session.state = 'browsing';
                session.selectedFile = null;
                await sender.sendText(userId, contextToken, '已取消。继续浏览：');
                await showCurrentFolder(userId, contextToken, session, quarkClient, sender);
            }
            return;
        }

        // Route input
        let folderData;
        try {
            folderData = await quarkClient.listFolder(session.currentPath);
        } catch (err) {
            if (err.status === 401) {
                await sender.sendText(userId, contextToken,
                    '⚠️ 夸克网盘登录已过期，请联系管理员更新 Cookie。');
                return;
            }
            logger.error('Folder listing failed', { error: err.message });
            await sender.sendText(userId, contextToken, '获取文件夹内容失败，请稍后重试。');
            return;
        }

        const route = routeInput(text, folderData, session.currentPath, session._page || 0);

        switch (route.action) {
            case 'navigate':
                session.currentPath = route.targetPath;
                session._page = 0;
                session.state = 'browsing';
                await showCurrentFolder(userId, contextToken, session, quarkClient, sender);
                break;

            case 'select_file':
                session.selectedFile = route.selectedFile;
                session.state = 'awaiting_download_confirm';
                await sender.sendText(userId, contextToken,
                    `确认下载 「${route.selectedFile.filename}」？\n回复 y 确认，其他键取消`);
                break;

            case 'back':
            case 'browse_root':
                session.currentPath = '/';
                session._page = 0;
                session.state = 'browsing';
                await showCurrentFolder(userId, contextToken, session, quarkClient, sender);
                break;

            case 'prev_page':
                session._page = Math.max(0, (session._page || 0) - 1);
                await sender.sendText(userId, contextToken,
                    renderMenu(folderData, session._page));
                break;

            case 'next_page': {
                const items = [...folderData.folders, ...folderData.files];
                const maxPage = Math.ceil(items.length / 8) - 1;
                session._page = Math.min(maxPage, (session._page || 0) + 1);
                await sender.sendText(userId, contextToken,
                    renderMenu(folderData, session._page));
                break;
            }

            case 'search':
                await handleSearch(userId, contextToken, route.query,
                    session, quarkClient, sender);
                break;

            case 'reset':
                sessionManager.reset(userId);
                await sender.sendText(userId, contextToken, '已重置。输入任意内容开始浏览：');
                break;

            case 'invalid':
                await sender.sendText(userId, contextToken,
                    route.message + '\n\n' + renderMenu(folderData, session._page || 0));
                break;

            default:
                // First message / fallback: show current folder
                await showCurrentFolder(userId, contextToken, session, quarkClient, sender);
        }
    };
}

async function showCurrentFolder(userId, contextToken, session, quarkClient, sender) {
    try {
        const data = await quarkClient.listFolder(session.currentPath);
        const menu = renderMenu(data, session._page || 0);
        await sender.sendText(userId, contextToken, menu);
    } catch (err) {
        if (err.status === 401) {
            await sender.sendText(userId, contextToken, '⚠️ 夸克网盘登录已过期，请联系管理员更新 Cookie。');
        } else {
            await sender.sendText(userId, contextToken, '获取文件夹失败，请稍后重试。');
        }
    }
}

async function handleDownload(userId, contextToken, session, quarkClient, sender) {
    const { fid, filename } = session.selectedFile;
    session.state = 'browsing';
    session.selectedFile = null;

    try {
        await sender.sendText(userId, contextToken, `⏳ 正在下载 「${filename}」...`);
        const task = await quarkClient.submitDownload(fid, filename);
        const result = await quarkClient.waitForDownload(task.task_id);
        await sender.sendFile(userId, contextToken, result.local_path);
        await sender.sendText(userId, contextToken,
            `✅ 「${filename}」发送完成！继续浏览：`);
    } catch (err) {
        logger.error('Download failed', { error: err.message });
        await sender.sendText(userId, contextToken, `下载失败: ${err.message}`);
    }

    // Show menu again
    await showCurrentFolder(userId, contextToken, session, quarkClient, sender);
}

async function handleSearch(userId, contextToken, query, session, quarkClient, sender) {
    try {
        await sender.sendText(userId, contextToken, `🔍 搜索: "${query}" ...`);
        const data = await quarkClient.searchFiles(query, session.currentPath);
        const results = data.results || [];

        if (results.length === 0) {
            await sender.sendText(userId, contextToken,
                `未找到匹配 "${query}" 的文件\n\n输入内容继续浏览：`);
            await showCurrentFolder(userId, contextToken, session, quarkClient, sender);
            return;
        }

        session.searchResults = results;
        session.state = 'search_results';

        const lines = [];
        lines.push(`🔍 "${query}" 找到 ${results.length} 个结果:`);
        lines.push('───────────────');
        results.forEach((r, i) => {
            const icon = r.is_dir ? '📁' : '📄';
            const suffix = !r.is_dir ? ` [${r.size}]` : '';
            lines.push(`[${i + 1}] ${icon} ${r.name}${suffix}`);
            lines.push(`     📂 ${r.path}`);
        });
        lines.push('───────────────');
        lines.push('回复数字序号选择文件下载 | 输入 s 关键词 继续搜索');

        await sender.sendText(userId, contextToken, lines.join('\n'));
    } catch (err) {
        logger.error('Search failed', { error: err.message });
        await sender.sendText(userId, contextToken, '搜索失败，请稍后重试。');
    }
}

function extractText(items) {
    return items
        .filter(i => i.type === 1 && i.text_item)
        .map(i => i.text_item.text)
        .join('\n');
}
