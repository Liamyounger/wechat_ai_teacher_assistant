import { homedir } from 'node:os';
import { join } from 'node:path';

export const DATA_DIR = process.env.WCC_DATA_DIR || join(homedir(), '.wechat-quark-bot');
export const CDN_BASE_URL = 'https://novac2c.cdn.weixin.qq.com/c2c';
export const CONFIG_PATH = join(DATA_DIR, 'config');
