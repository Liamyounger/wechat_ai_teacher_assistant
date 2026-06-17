import { getItems } from './renderer.js';

/**
 * Parse user text input and determine the action.
 */
export function routeInput(text, folderData, currentPath, currentPage) {
    const input = text.trim().toLowerCase();

    if (input === '0' || input === '返回' || input === 'back') {
        if (currentPath === '/') {
            return { action: 'browse_root' };
        }
        const parent = currentPath.substring(0, currentPath.lastIndexOf('/')) || '/';
        return { action: 'navigate', targetPath: parent };
    }

    if (input === 'p' || input === '上页') {
        return { action: 'prev_page', page: Math.max(0, currentPage - 1) };
    }

    if (input === 'n' || input === '下页') {
        return { action: 'next_page', page: currentPage + 1 };
    }

    if (input === 'r' || input === '重置' || input === 'reset') {
        return { action: 'reset' };
    }

    // Search: "s keyword" or "搜索 keyword"
    const searchMatch = input.match(/^(?:s|搜索|search)\s+(.+)/i);
    if (searchMatch) {
        return { action: 'search', query: searchMatch[1].trim() };
    }

    // Numeric selection
    const num = parseInt(input, 10);
    if (isNaN(num) || num < 1) {
        return { action: 'invalid', message: '请回复数字选择，或回复 0 返回上级' };
    }

    const items = getItems(folderData);
    const pageSize = 8;
    const pageStart = currentPage * pageSize;
    const pageItems = items.slice(pageStart, pageStart + pageSize);

    if (num > pageItems.length) {
        return { action: 'invalid', message: `请输入 1-${pageItems.length} 之间的数字` };
    }

    const selected = pageItems[num - 1];

    if (selected.type === 'folder') {
        const target = currentPath === '/' ? `/${selected.name}` : `${currentPath}/${selected.name}`;
        return { action: 'navigate', targetPath: target };
    }

    return {
        action: 'select_file',
        selectedFile: { fid: selected.fid, filename: selected.name },
    };
}
