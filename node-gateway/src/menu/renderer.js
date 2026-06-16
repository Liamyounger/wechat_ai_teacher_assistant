/**
 * Format a folder listing response from Python service into a WeChat text menu.
 *
 * @param {Object} data - Response from GET /api/v1/folder
 * @param {string} data.path
 * @param {Array<{name: string, fid: string, has_children?: boolean}>} data.folders
 * @param {Array<{name: string, fid: string, size: string}>} data.files
 * @param {number} [page=0]
 * @param {number} [pageSize=8]
 * @returns {string}
 */
export function renderMenu(data, page = 0, pageSize = 8) {
    const { path, folders, files } = data;
    const lines = [];
    const allItems = [
        ...folders.map(f => ({ ...f, type: 'folder' })),
        ...files.map(f => ({ ...f, type: 'file' })),
    ];

    const totalPages = Math.ceil(allItems.length / pageSize);
    const start = page * pageSize;
    const pageItems = allItems.slice(start, start + pageSize);

    lines.push(`📂 ${path || '/'}`);
    lines.push('───────────────');

    if (pageItems.length === 0) {
        lines.push('(空文件夹)');
    } else {
        pageItems.forEach((item, i) => {
            const num = start + i + 1;
            const icon = item.type === 'folder' ? '📁' : '📄';
            const suffix = item.type === 'file' ? ` [${item.size}]` : '';
            lines.push(`[${num}] ${icon} ${item.name}${suffix}`);
        });
    }

    lines.push('───────────────');
    const nav = ['[0] 🔙 返回上级'];
    if (totalPages > 1) {
        if (page > 0) nav.push('[p] ⬆ 上页');
        if (page < totalPages - 1) nav.push('[n] ⬇ 下页');
    }
    nav.push('[r] 🔄 重置');
    lines.push(nav.join('  '));

    return lines.join('\n');
}

/**
 * Get all items flattened from folder data (for lookup by index).
 */
export function getItems(data) {
    return [
        ...data.folders.map(f => ({ ...f, type: 'folder' })),
        ...data.files.map(f => ({ ...f, type: 'file' })),
    ];
}
