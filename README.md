# wechat_ai_teacher_assistant

微信 AI 教师助手 —— 用户在微信中通过菜单导航夸克网盘文件夹，选择试卷/文件后以 PDF 文件消息发送到微信。支持查询试卷、排课表、PDF 发送等功能。

## 架构

```
微信 iLink API
    ↕ 长轮询
Node.js 消息网关 (:3000)
    ↕ HTTP REST (localhost:8000)
Python FastAPI 服务 — 夸克网盘操作
    ↕ HTTPS + Cookie
夸克云存储 API (drive-pc.quark.cn)
```

- **Node.js 网关**：复用 wechat-claude-code 的 iLink 通信层，处理消息收发、菜单会话管理、文件上传发送
- **Python 服务**：基于 FastAPI，负责夸克网盘文件夹浏览、文件下载（带反爬）、Cookie 维护
- 服务器无需浏览器 —— Cookie 在本地 PC 用 Playwright 扫码登录一次后导出上传

## 前置条件

**服务器（Linux）：**
- Docker + Docker Compose
- 2 vCPU / 2 GiB RAM（最低）
- 夸克网盘账号

**本地 PC（仅首次配置用）：**
- Python 3.10+ + Playwright
- 有图形界面（用于扫码登录）

## 快速开始（Linux 服务器）

### 1. 克隆项目

```bash
git clone <repo-url> wechat-quark-bot
cd wechat-quark-bot
```

### 2. 配置微信机器人

编辑 `node-gateway/config/bot.json`，填入你的 iLink Bot 凭据：

```json
{
  "botToken": "f21e28a8c586@im.bot:0600004c987122...",
  "accountId": "f21e28a8c586@im.bot",
  "baseUrl": "https://ilinkai.weixin.qq.com",
  "quarkServiceUrl": "http://python-service:8000"
}
```

### 3. 导出夸克 Cookie（在本地 PC 执行）

```bash
cd exports
pip install -r requirements.txt
playwright install firefox
python export_cookies.py
```

浏览器会打开 `pan.quark.cn`，扫码登录后按 Enter。Cookie 自动保存到 `python-service/config/cookies.json`。

将 `python-service/config/cookies.json` 上传到服务器：

```bash
scp python-service/config/cookies.json user@your-server:/path/to/wechat-quark-bot/python-service/config/
```

### 4. 启动服务

```bash
chmod +x deploy.sh
./deploy.sh
```

部署脚本会检查配置文件、构建 Docker 镜像并启动两个容器。

### 5. 验证运行

```bash
# 查看容器状态
docker compose ps

# 查看日志
docker compose logs -f

# 测试 Python 服务健康检查
curl http://localhost:8000/health
# → {"ok":true}
```

### 6. 开始使用

在微信中向机器人发送任意消息，会收到夸克网盘的文件夹菜单。回复数字导航，选择 PDF 文件后回复 `y` 确认下载。

```
📂 /试卷
───────────────
[1] 📁 高一/
[2] 📁 高二/
[3] 📁 高三/
───────────────
[0] 🔙 返回上级  [r] 🔄 重置
```

## 菜单操作说明

| 输入 | 功能 |
|------|------|
| `1-8` | 进入文件夹或选择文件 |
| `0` / `返回` | 返回上一级 |
| `p` / `上页` | 上一页 |
| `n` / `下页` | 下一页 |
| `r` / `重置` | 回到根目录 |
| `y` / `确认` | 确认下载选中的文件 |

## 目录结构

```
wechat-quark-bot/
├── docker-compose.yml           # Docker 编排
├── deploy.sh                    # 一键部署脚本
├── python-service/              # Python 夸克网盘服务
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── config/
│   │   ├── settings.py          # 配置（支持环境变量 QUARK_*）
│   │   └── cookies.json         # ★ 夸克 Cookie（从本地 PC 导出）
│   └── src/
│       ├── main.py              # FastAPI 入口
│       ├── routes.py            # API 路由
│       ├── quark/
│       │   ├── api.py           # 夸克 API 客户端
│       │   └── cookie.py        # Cookie 管理器
│       └── download/
│           ├── queue.py         # 下载任务队列
│           └── fetcher.py       # 文件下载器（重试+UA轮换）
├── node-gateway/                # Node.js 微信消息网关
│   ├── Dockerfile
│   ├── package.json
│   ├── config/
│   │   └── bot.json             # ★ 微信机器人配置
│   └── src/
│       ├── index.js             # 入口
│       ├── bot.js               # 消息处理器
│       ├── wechat/              # iLink API 通信层
│       ├── session/             # 用户会话管理
│       ├── menu/                # 菜单渲染+路由
│       └── quark/               # Python 服务 HTTP 客户端
└── exports/
    ├── export_cookies.py        # 本地 PC Cookie 导出工具
    └── requirements.txt
```

## 配置环境变量

### Python 服务（`QUARK_` 前缀）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `QUARK_COOKIES_PATH` | `config/cookies.json` | Cookie 文件路径 |
| `QUARK_DOWNLOAD_DIR` | `/tmp/quark_downloads` | 下载临时目录 |
| `QUARK_DOWNLOAD_TTL_SECONDS` | `300` | 下载文件保留时间（秒） |
| `QUARK_LOG_LEVEL` | `INFO` | 日志级别 |

### Node.js 网关

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `WCC_DATA_DIR` | `~/.wechat-quark-bot` | 数据目录 |

## Cookie 过期处理

夸克 Cookie 有效期通常为数天至一周。Python 服务在每次请求时会检查过期状态：

1. 如果 Cookie 过期，返回 401 给 Node.js
2. Node.js 向用户显示「夸克网盘登录已过期，请联系管理员更新 Cookie」
3. 管理员在本地 PC 重新运行 `python exports/export_cookies.py`，将新 `cookies.json` 上传到服务器
4. 重启服务：`docker compose restart`

## 故障排查

**服务无法启动：**
```bash
docker compose logs          # 查看所有日志
docker compose ps            # 查看容器状态
```

**微信消息无响应：**
- 检查 `node-gateway/config/bot.json` 中的 botToken 是否正确
- 查看网关日志：`docker compose logs wechat-gateway`

**文件夹显示为空：**
- 确认 `cookies.json` 已正确上传且非空
- 测试 API：`curl "http://localhost:8000/api/v1/folder?path=/试卷"`
- 如果返回 401，Cookie 已过期，需要重新导出

**文件下载失败：**
- 夸克下载链接有时效性（几小时），确保拿到链接后尽快下载
- 串行队列同一时间只下载一个文件，多个用户需排队
- 查看 Python 服务日志：`docker compose logs quark-service`

**文件发送失败：**
- iLink 文件大小限制 25MB，超过此大小的文件无法通过微信发送
- 如有大量文件发送，可能触发微信限频，等待后重试

GitHub: [https://github.com/Liamyounger/wechat_ai_teacher_assistant](https://github.com/Liamyounger/wechat_ai_teacher_assistant)
