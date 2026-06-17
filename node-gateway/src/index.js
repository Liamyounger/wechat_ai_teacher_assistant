import process from 'node:process';
import { mkdirSync, writeFileSync, unlinkSync } from 'node:fs';
import { join, basename } from 'node:path';
import { spawnSync } from 'node:child_process';
import { WeChatApi } from './wechat/api.js';
import { loadAccount, loadLatestAccount, loadConfig } from './wechat/accounts.js';
import { startQrLogin, waitForQrScan } from './wechat/login.js';
import { createMonitor } from './wechat/monitor.js';
import { createSender } from './wechat/send.js';
import { createSessionManager } from './session/manager.js';
import { createHandler } from './bot.js';
import { QuarkServiceClient } from './quark/client.js';
import { DATA_DIR } from './constants.js';
import { logger } from './logger.js';

// ── Setup: QR code login ────────────────────────────────────────────────────

function openFile(filePath) {
    const platform = process.platform;
    let cmd, args;
    if (platform === 'darwin') {
        cmd = 'open'; args = [filePath];
    } else if (platform === 'win32') {
        cmd = 'cmd'; args = ['/c', 'start', '', filePath];
    } else {
        cmd = 'xdg-open'; args = [filePath];
    }
    spawnSync(cmd, args, { stdio: 'ignore' });
}

async function runSetup() {
    mkdirSync(DATA_DIR, { recursive: true });
    const QR_PATH = join(DATA_DIR, 'qrcode.png');
    console.log('正在设置...\n');

    while (true) {
        const { qrcodeUrl, qrcodeId } = await startQrLogin();

        const isHeadlessLinux = process.platform === 'linux' &&
            !process.env.DISPLAY && !process.env.WAYLAND_DISPLAY;

        if (isHeadlessLinux) {
            try {
                const qrcodeTerminal = await import('qrcode-terminal');
                console.log('请用微信扫描下方二维码：\n');
                qrcodeTerminal.default.generate(qrcodeUrl, { small: true });
                console.log();
                console.log('二维码链接：', qrcodeUrl);
                console.log();
            } catch {
                console.log('无法在终端显示二维码，请访问链接：');
                console.log(qrcodeUrl);
                console.log();
            }
        } else {
            const QRCode = await import('qrcode');
            const pngData = await QRCode.toBuffer(qrcodeUrl, { type: 'png', width: 400, margin: 2 });
            writeFileSync(QR_PATH, pngData);
            openFile(QR_PATH);
            console.log('已打开二维码图片，请用微信扫描：');
            console.log(`图片路径: ${QR_PATH}\n`);
        }

        console.log('等待扫码绑定...');
        try {
            await waitForQrScan(qrcodeId);
            console.log('\n绑定成功!');
            break;
        } catch (err) {
            if (err.message?.includes('expired')) {
                console.log('二维码已过期，正在刷新...\n');
                continue;
            }
            throw err;
        }
    }

    try { unlinkSync(QR_PATH); } catch { /* ignore */ }

    // Copy quarkServiceUrl from config if available
    const botConfig = loadConfig();
    const quarkServiceUrl = botConfig?.quarkServiceUrl || 'http://python-service:8000';
    console.log(`夸克服务地址: ${quarkServiceUrl}`);
    console.log('\n运行 npm start 启动服务');
}

// ── Daemon ───────────────────────────────────────────────────────────────────

async function runDaemon() {
    // Try bot.json config first, then auto-load from accounts
    let botConfig = loadConfig();
    if (!botConfig?.botToken || botConfig.botToken === 'YOUR_BOT_TOKEN_HERE') {
        const account = loadLatestAccount();
        if (!account) {
            console.error('未找到账号，请先运行 node src/index.js setup');
            process.exit(1);
        }
        botConfig = {
            botToken: account.botToken,
            accountId: account.accountId,
            baseUrl: account.baseUrl,
            quarkServiceUrl: process.env.QUARK_SERVICE_URL || 'http://python-service:8000',
        };
    }

    const account = { accountId: botConfig.accountId, botToken: botConfig.botToken, baseUrl: botConfig.baseUrl };
    const api = new WeChatApi(account.botToken, account.baseUrl);
    const sender = createSender(api, account.accountId);
    const sessionManager = createSessionManager();
    const quarkClient = new QuarkServiceClient(botConfig.quarkServiceUrl || 'http://127.0.0.1:8000');
    const handleMessage = createHandler(sessionManager, quarkClient, sender);

    const messageQueue = [];
    let processing = false;

    async function drainQueue() {
        if (processing) return;
        processing = true;
        while (messageQueue.length > 0) {
            const { msg, contextToken } = messageQueue.shift();
            try {
                await handleMessage(msg, contextToken);
            } catch (err) {
                logger.error('Handler error', { error: err.message });
            }
        }
        processing = false;
    }

    const monitor = createMonitor(api, {
        onMessage: async (msg) => {
            const ctx = msg.context_token ?? '';
            messageQueue.push({ msg, contextToken: ctx });
            drainQueue();
        },
        onSessionExpired: () => {
            console.error('微信会话已过期，请重新运行 node src/index.js setup');
        },
    });

    function shutdown() {
        logger.info('Shutting down...');
        monitor.stop();
        process.exit(0);
    }
    process.on('SIGINT', shutdown);
    process.on('SIGTERM', shutdown);

    mkdirSync(DATA_DIR, { recursive: true });
    logger.info('Daemon started', { accountId: account.accountId });
    console.log(`WeChat Quark Bot started (account: ${account.accountId})`);
    await monitor.run();
}

// ── CLI ──────────────────────────────────────────────────────────────────────

const cmd = process.argv[2];
if (cmd === 'setup') {
    runSetup().catch(err => {
        logger.error('Setup failed', { error: err.message });
        console.error('设置失败:', err);
        process.exit(1);
    });
} else {
    runDaemon().catch(err => {
        logger.error('Fatal', { error: err.message });
        console.error('Fatal error:', err);
        process.exit(1);
    });
}
