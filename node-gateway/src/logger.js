const LEVELS = { DEBUG: 10, INFO: 20, WARN: 30, ERROR: 40 };
const currentLevel = LEVELS[process.env.LOG_LEVEL?.toUpperCase()] ?? LEVELS.INFO;

function format(level, msg, extra) {
    const ts = new Date().toISOString();
    const base = `${ts} ${level} ${msg}`;
    if (extra) return `${base} ${JSON.stringify(extra)}`;
    return base;
}

export const logger = {
    debug: (msg, extra) => { if (LEVELS.DEBUG >= currentLevel) console.error(format('DEBUG', msg, extra)); },
    info:  (msg, extra) => { if (LEVELS.INFO >= currentLevel) console.error(format('INFO', msg, extra)); },
    warn:  (msg, extra) => { if (LEVELS.WARN >= currentLevel) console.error(format('WARN', msg, extra)); },
    error: (msg, extra) => { if (LEVELS.ERROR >= currentLevel) console.error(format('ERROR', msg, extra)); },
};
