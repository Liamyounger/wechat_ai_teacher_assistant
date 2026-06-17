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

        // Handle download confirmation
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
                session.currentPath = '/试卷';
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

function extractText(items) {
    return items
        .filter(i => i.type === 1 && i.text_item)
        .map(i => i.text_item.text)
        .join('\n');
}
