import process from 'node:process';
import { mkdirSync } from 'node:fs';
import { WeChatApi } from './wechat/api.js';
import { loadConfig } from './wechat/accounts.js';
import { createMonitor } from './wechat/monitor.js';
import { createSender } from './wechat/send.js';
import { createSessionManager } from './session/manager.js';
import { createHandler } from './bot.js';
import { QuarkServiceClient } from './quark/client.js';
import { DATA_DIR } from './constants.js';
import { logger } from './logger.js';

async function runDaemon(botConfig) {
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
            console.error('WeChat session expired. Please re-run setup.');
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

const cmd = process.argv[2];
if (cmd === 'setup') {
    console.log('Setup: Edit config/bot.json with your bot token, then run "npm start"');
    process.exit(0);
} else {
    // Validate config synchronously so import-time errors propagate to callers
    const botConfig = loadConfig();
    if (!botConfig?.botToken || botConfig.botToken === 'YOUR_BOT_TOKEN_HERE') {
        console.error('Please configure config/bot.json with your bot token');
        throw new Error('YOUR_BOT_TOKEN_HERE: Please configure config/bot.json with your bot token');
    }
    runDaemon(botConfig).catch(err => {
        logger.error('Fatal', { error: err.message });
        console.error('Fatal error:', err);
        process.exit(1);
    });
}
