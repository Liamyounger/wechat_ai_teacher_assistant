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
                    session.selectedFile = { fid: selected.fid, filename: selected.name, size: selected.size || '' };
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

        // Handle article search results selection
        if (session.state === 'article_results') {
            const num = parseInt(text.trim(), 10);
            if (!isNaN(num) && num >= 1 && session.articleResults &&
                num <= session.articleResults.length) {
                const selected = session.articleResults[num - 1];
                await sender.sendText(userId, contextToken,
                    `🔍 正在解析文章 「${selected.title}」...`);
                try {
                    const extracted = await quarkClient.extractArticleLinks(selected.sogou_url);
                    session.extractedLinks = extracted;
                    session.state = 'article_links';
                    const linksText = formatArticleLinks(extracted);
                    await sender.sendText(userId, contextToken, linksText);
                } catch (err) {
                    logger.error('Article extraction failed', { error: err.message });
                    await sender.sendText(userId, contextToken,
                        `解析文章失败: ${err.message}\n\n可能原因：文章链接已过期或无法访问。`);
                    session.state = 'browsing';
                }
                return;
            }
            // p/n pagination for article results
            if (text === 'p' || text === '上页') {
                session._articlePage = Math.max(0, (session._articlePage || 0) - 1);
                await sender.sendText(userId, contextToken,
                    formatArticleResults(session.articleResults, session._articlePage));
                return;
            }
            if (text === 'n' || text === '下页') {
                const maxPage = Math.ceil((session.articleResults?.length || 0) / 8) - 1;
                session._articlePage = Math.min(maxPage, (session._articlePage || 0) + 1);
                await sender.sendText(userId, contextToken,
                    formatArticleResults(session.articleResults, session._articlePage));
                return;
            }
            // Any other input exits article results
            session.state = 'browsing';
            session.articleResults = null;
            session._articlePage = 0;
        }

        // Handle article links selection
        if (session.state === 'article_links') {
            const num = parseInt(text.trim(), 10);
            if (!isNaN(num) && num >= 1 && session.extractedLinks?.links &&
                num <= session.extractedLinks.links.length) {
                const selected = session.extractedLinks.links[num - 1];
                const extractCodes = session.extractedLinks.extract_codes || [];
                const isQuark = selected.platform === '夸克网盘' || selected.url.includes('pan.quark.cn');
                if (isQuark) {
                    // For Quark links, offer to browse the shared folder
                    session.shareUrl = selected.url;
                    session.sharePath = '';
                    session._sharePage = 0;
                    session.state = 'share_browsing';
                    try {
                        await sender.sendText(userId, contextToken,
                            `📦 正在访问夸克分享...`);
                        const shareData = await quarkClient.browseShare(session.shareUrl);
                        const shareMenu = formatShareMenu(shareData, session._sharePage);
                        await sender.sendText(userId, contextToken, shareMenu);
                    } catch (err) {
                        await sender.sendText(userId, contextToken,
                            `访问分享失败: ${err.message}\n\n直接链接：${selected.url}\n请在夸克 App 中打开后转存到网盘。`);
                        session.state = 'browsing';
                    }
                } else {
                    session.state = 'browsing';
                    session.extractedLinks = null;
                    const codes = extractCodes.length
                        ? `\n提取码: ${extractCodes.join(', ')}` : '';
                    await sender.sendText(userId, contextToken,
                        `🔗 ${selected.platform} 分享链接：\n${selected.url}${codes}\n\n输入内容继续浏览：`);
                    await showCurrentFolder(userId, contextToken, session, quarkClient, sender);
                }
                return;
            }
            // Any other input exits
            session.state = 'browsing';
            session.extractedLinks = null;
        }

        // Handle share browsing (navigating inside a Quark share)
        if (session.state === 'share_browsing') {
            if (text === '0' || text === '返回' || text === 'back') {
                session.state = 'browsing';
                session.shareUrl = null;
                await sender.sendText(userId, contextToken, '已退出分享浏览。输入内容继续：');
                await showCurrentFolder(userId, contextToken, session, quarkClient, sender);
                return;
            }
            if (text === 'p' || text === '上页') {
                session._sharePage = Math.max(0, (session._sharePage || 0) - 1);
                try {
                    const data = await quarkClient.browseShare(session.shareUrl, session.sharePath || '');
                    await sender.sendText(userId, contextToken, formatShareMenu(data, session._sharePage));
                } catch (err) {
                    await sender.sendText(userId, contextToken, `刷新失败: ${err.message}`);
                }
                return;
            }
            if (text === 'n' || text === '下页') {
                session._sharePage = (session._sharePage || 0) + 1;
                try {
                    const data = await quarkClient.browseShare(session.shareUrl, session.sharePath || '');
                    const items = [...(data.folders || []), ...(data.files || [])];
                    const maxPage = Math.ceil(items.length / 8) - 1;
                    session._sharePage = Math.min(maxPage, session._sharePage);
                    await sender.sendText(userId, contextToken, formatShareMenu(data, session._sharePage));
                } catch (err) {
                    await sender.sendText(userId, contextToken, `刷新失败: ${err.message}`);
                }
                return;
            }

            // Numeric selection
            const num = parseInt(text.trim(), 10);
            if (!isNaN(num) && num >= 1) {
                try {
                    const data = await quarkClient.browseShare(session.shareUrl, session.sharePath || '');
                    const items = [...(data.folders || []), ...(data.files || [])];
                    const pageSize = 8;
                    const start = (session._sharePage || 0) * pageSize;
                    const pageItems = items.slice(start, start + pageSize);
                    if (num <= pageItems.length) {
                        const selected = pageItems[num - 1];
                        if (selected.is_dir) {
                            session.sharePath = selected.fid;
                            session._sharePage = 0;
                            const subData = await quarkClient.browseShare(session.shareUrl, selected.fid);
                            await sender.sendText(userId, contextToken, formatShareMenu(subData, 0));
                        } else {
                            // Download file from share
                            session.state = 'awaiting_download_confirm';
                            session.selectedFile = {
                                fid: selected.fid,
                                filename: selected.name,
                                size: selected.size_display || '',
                                fromShare: true,
                                shareUrl: session.shareUrl,
                            };
                            await sender.sendText(userId, contextToken,
                                `确认下载 「${selected.name}」？\n回复 y 确认，其他键取消`);
                        }
                        return;
                    }
                } catch (err) {
                    await sender.sendText(userId, contextToken, `操作失败: ${err.message}`);
                }
            }
            // Invalid input in share browsing
            try {
                const data = await quarkClient.browseShare(session.shareUrl, session.sharePath || '');
                await sender.sendText(userId, contextToken,
                    '请回复数字选择文件/文件夹\n\n' + formatShareMenu(data, session._sharePage || 0));
            } catch { /* ignore */ }
            return;
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

            case 'article_search':
                await handleArticleSearch(userId, contextToken, route.query,
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

function exceedsSizeLimit(sizeStr) {
    if (!sizeStr) return false;
    const match = sizeStr.match(/^([\d.]+)\s*(MB|GB|KB)/i);
    if (!match) return false;
    const num = parseFloat(match[1]);
    const unit = match[2].toUpperCase();
    if (unit === 'GB') return true;
    if (unit === 'MB' && num >= 200) return true;
    return false;
}

async function handleDownload(userId, contextToken, session, quarkClient, sender) {
    const { fid, filename, size, fromShare, shareUrl } = session.selectedFile;
    session.state = 'browsing';
    session.selectedFile = null;

    if (!fromShare && exceedsSizeLimit(size)) {
        await sender.sendText(userId, contextToken,
            `⚠️ 「${filename}」(${size}) 超过 200MB，不支持发送。`);
        await showCurrentFolder(userId, contextToken, session, quarkClient, sender);
        return;
    }

    try {
        await sender.sendText(userId, contextToken, `⏳ 正在下载 「${filename}」...`);
        let task, result;
        if (fromShare) {
            task = await quarkClient.submitShareDownload(shareUrl, fid, filename);
        } else {
            task = await quarkClient.submitDownload(fid, filename);
        }
        result = await quarkClient.waitForDownload(task.task_id);

        // Handle split PDFs or single file
        const parts = result.parts && result.parts.length > 1 ? result.parts : [result.local_path];

        if (parts.length === 1) {
            await sender.sendFile(userId, contextToken, parts[0]);
            await sender.sendText(userId, contextToken,
                `✅ 「${filename}」发送完成！继续浏览：`);
        } else {
            await sender.sendText(userId, contextToken,
                `📦 「${filename}」已拆分为 ${parts.length} 个文件，正在依次发送...`);
            for (let i = 0; i < parts.length; i++) {
                await sender.sendText(userId, contextToken,
                    `⏳ 发送中 (${i + 1}/${parts.length})...`);
                await sender.sendFile(userId, contextToken, parts[i]);
            }
            await sender.sendText(userId, contextToken,
                `✅ 「${filename}」全部 ${parts.length} 个文件发送完成！继续浏览：`);
        }
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

async function handleArticleSearch(userId, contextToken, query, session, quarkClient, sender) {
    try {
        await sender.sendText(userId, contextToken, `🔍 正在搜索微信公众号文章：「${query}」...`);
        const data = await quarkClient.searchArticles(query);
        const articles = data.articles || [];

        if (articles.length === 0) {
            await sender.sendText(userId, contextToken,
                `未找到与「${query}」相关的公众号文章。\n\n输入内容继续浏览：`);
            await showCurrentFolder(userId, contextToken, session, quarkClient, sender);
            return;
        }

        session.articleResults = articles;
        session._articlePage = 0;
        session.state = 'article_results';

        const text = formatArticleResults(articles, 0);
        await sender.sendText(userId, contextToken, text);
    } catch (err) {
        logger.error('Article search failed', { error: err.message });
        await sender.sendText(userId, contextToken,
            `文章搜索失败: ${err.message}\n\n输入内容继续浏览：`);
    }
}

function formatArticleResults(articles, page = 0, pageSize = 8) {
    const lines = [];
    const totalPages = Math.ceil(articles.length / pageSize) || 1;
    const start = page * pageSize;
    const pageItems = articles.slice(start, start + pageSize);

    lines.push(`📰 公众号文章搜索结果 (${articles.length} 篇)`);
    lines.push(`第 ${page + 1}/${totalPages} 页`);
    lines.push('───────────────');

    pageItems.forEach((a, i) => {
        const num = start + i + 1;
        lines.push(`[${num}] ${a.title}`);
        lines.push(`    🖊 ${a.account}  📅 ${a.date || '未知'}`);
        if (a.summary) lines.push(`    ${a.summary.slice(0, 80)}`);
    });

    lines.push('───────────────');
    const nav = [];
    if (totalPages > 1) {
        if (page > 0) nav.push('[p] ⬆ 上页');
        if (page < totalPages - 1) nav.push('[n] ⬇ 下页');
    }
    nav.push('[0/其他键] 返回浏览');
    lines.push(nav.join('  '));
    lines.push('回复数字序号提取该文章中的分享链接');

    return lines.join('\n');
}

function formatArticleLinks(extracted) {
    const lines = [];
    lines.push(`📄 ${extracted.title || '文章'}`);
    if (extracted.account) lines.push(`🖊 ${extracted.account}`);
    lines.push('');

    const { links, extract_codes } = extracted;
    if (links.length === 0) {
        lines.push('❌ 该文章中未找到分享链接。');
        lines.push('');
        lines.push('输入内容继续浏览...');
        return lines.join('\n');
    }

    lines.push(`📎 找到 ${links.length} 个分享链接：`);
    lines.push('───────────────');
    links.forEach((l, i) => {
        lines.push(`[${i + 1}] 🔗 ${l.platform}`);
        lines.push(`    ${l.url}`);
        if (l.platform === '百度网盘' && extract_codes?.length) {
            lines.push(`    🔑 提取码: ${extract_codes.join(', ')}`);
        }
    });
    lines.push('───────────────');
    lines.push('回复数字序号查看链接详情 | 其他键返回浏览');

    return lines.join('\n');
}

function formatShareMenu(data, page = 0, pageSize = 8) {
    const lines = [];
    const folders = data.folders || [];
    const files = data.files || [];
    const allItems = [
        ...folders.map(f => ({ ...f, type: 'folder' })),
        ...files.map(f => ({ ...f, type: 'file' })),
    ];
    const totalPages = Math.ceil(allItems.length / pageSize) || 1;
    const start = page * pageSize;
    const pageItems = allItems.slice(start, start + pageSize);

    lines.push('📦 夸克分享内容');
    lines.push(`📁 ${folders.length} 个文件夹  📄 ${files.length} 个文件`);
    lines.push(`第 ${page + 1}/${totalPages} 页`);
    lines.push('───────────────');

    if (pageItems.length === 0) {
        lines.push('(空文件夹)');
    } else {
        pageItems.forEach((item, i) => {
            const num = start + i + 1;
            const icon = item.type === 'folder' ? '📁' : '📄';
            const suffix = item.type === 'file' ? ` [${item.size_display || ''}]` : '';
            lines.push(`[${num}] ${icon} ${item.name}${suffix}`);
        });
    }

    lines.push('───────────────');
    const nav = [];
    if (totalPages > 1) {
        if (page > 0) nav.push('[p] ⬆ 上页');
        if (page < totalPages - 1) nav.push('[n] ⬇ 下页');
    }
    nav.push('[0] 🔙 退出分享');
    lines.push(nav.join('  '));
    lines.push('回复数字选择文件下载');

    return lines.join('\n');
}

function extractText(items) {
    return items
        .filter(i => i.type === 1 && i.text_item)
        .map(i => i.text_item.text)
        .join('\n');
}
