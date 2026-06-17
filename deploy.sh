#!/bin/bash
set -e

echo "=== WeChat Quark Bot Deployment ==="

# Check prerequisites
command -v docker >/dev/null 2>&1 || { echo "Docker is required"; exit 1; }
command -v docker compose >/dev/null 2>&1 || { echo "Docker Compose is required"; exit 1; }

# Check config files
if [ ! -f "node-gateway/config/bot.json" ]; then
    echo "ERROR: node-gateway/config/bot.json not found."
    echo "Create it with your iLink bot token, e.g.:"
    echo '  {"botToken":"xxx@im.bot:xxx","accountId":"xxx@im.bot","baseUrl":"https://ilinkai.weixin.qq.com","quarkServiceUrl":"http://python-service:8000"}'
    exit 1
fi

if grep -q "YOUR_BOT_TOKEN_HERE" node-gateway/config/bot.json; then
    echo "ERROR: bot.json still has placeholder token. Edit it with your real token."
    exit 1
fi

if [ ! -f "python-service/config/cookies.json" ]; then
    echo "ERROR: python-service/config/cookies.json not found."
    echo "Run 'python exports/export_cookies.py' on a local PC first,"
    echo "then copy the resulting cookies.json to python-service/config/"
    exit 1
fi

echo "Building and starting services..."
docker compose up -d --build

echo ""
echo "Deployment complete. Check status with: docker compose ps"
echo "View logs with: docker compose logs -f"
