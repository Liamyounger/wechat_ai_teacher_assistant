# WeChat Quark Bot — Design Spec

**Date**: 2026-06-16  
**Status**: draft  
**Scope**: MVP — WeChat menu-based navigation → Quark cloud storage folder browsing → file download → PDF delivery

---

## 1. Overview

A Linux server application that connects a WeChat bot account to Quark cloud storage. Users scan a QR code to start interacting with the bot, navigate a folder hierarchy via menus, select files, and receive them as PDF file messages in WeChat.

### Constraints

| Constraint | Value |
|------------|-------|
| Server | 2 vCPU, 2 GiB RAM, Linux (Ubuntu Server minimal) |
| Memory budget | ~430 MB idle, ~600 MB peak |
| Bot platform | WeChat iLink AI Bot (existing account, token reused) |
| Cloud storage | Quark cloud storage (夸克网盘) |
| Browser on server | None (Playwright only on local PC for initial login) |

---

## 2. Architecture

```
WeChat iLink API
    │ (long-poll)
Node.js Gateway (:3000)    ← reuses wechat-claude-code iLink comm layer
    │ HTTP REST (localhost)
Python FastAPI (:8000)     ← reuses QuarkPanTool download/anti-scraping logic
    │ HTTPS + Cookie
Quark Cloud Storage API
```

### 2.1 Node.js Gateway

Responsibilities:
- Long-poll WeChat iLink API for incoming messages
- Manage per-user menu session state
- Route user selections (folder navigation vs. file download)
- Forward download requests to Python service
- Poll download progress and send file messages to users

Dependencies: Node.js 24, the iLink communication module adapted from wechat-claude-code.

### 2.2 Python FastAPI Service

Responsibilities:
- List folder contents (subfolders + files) from Quark cloud
- Download files with anti-scraping measures
- Maintain Quark cookie freshness (refresh + expiry alert)
- Clean up temporary download files (5-minute TTL)

Dependencies: Python 3.12+, FastAPI, httpx, playwright (local PC only for initial cookie export).

---

## 3. Internal API Contract

Base: `http://localhost:8000/api/v1`

### GET /folder?path=/试卷

Returns immediate children of the given path.

```json
{
  "path": "/试卷/高二",
  "folders": [
    {"name": "数学", "has_children": true},
    {"name": "语文", "has_children": true}
  ],
  "files": [
    {"name": "2025高二期中数学A卷.pdf", "size": "2.3MB", "file_id": "abc123"}
  ]
}
```

Error: `{"error": "path_not_found"}` | `{"error": "cookie_expired"}`

### POST /download

Submit a download task. Body: `{"file_id": "abc123", "filename": "xxx.pdf"}`  
Response: `{"task_id": "d4e5f6", "status": "queued"}`

### GET /download/{task_id}

Status poll. Response:
- `{"status": "queued"}` → `{"status": "downloading", "progress": 65}` → `{"status": "done", "local_path": "/tmp/quark_downloads/d4e5f6/xxx.pdf"}`
- `{"status": "failed", "error": "..."}`

### GET /health → `{"ok": true}`

---

## 4. Menu Session Model (Node.js)

```typescript
interface UserSession {
  userId: string;
  currentPath: string;
  state: "browsing" | "awaiting_download_confirm";
  selectedFile: { file_id: string; filename: string } | null;
  lastActivity: number; // Unix ms
}
```

### Navigation rules

- Folders: `📁` prefix, Files: `📄` prefix
- First item always `[0] 🔙 返回上级`
- Items numbered starting from 1
- >10 items → paginate with `[上页] [下页]`
- User sends number → navigate into folder or select file
- File selection → confirm prompt → download → send file → back to menu

### Session lifecycle

- Created on first message
- 30-minute idle timeout → auto-clean
- `/reset` or "重置" → reset to root

---

## 5. Quark Cookie Management (Python)

### Initial setup

1. Local PC: run `playwright` script → open browser → user scans QR code → export `cookies.json`
2. Copy `cookies.json` to server `config/cookies.json`
3. Python loads on startup

### Runtime

- Every Quark API request: attach cookies → if 401 → attempt refresh
- Refresh successful → update `cookies.json` → continue
- Refresh failed → return `{"error": "cookie_expired"}` → Node.js notifies admin via WeChat

### Cron health check

Cron job at 3:00 AM daily: call a lightweight Quark endpoint → 401 → alert admin early.

### Cookie file format

```json
{
  "cookies": [/* Playwright-exported cookie array */],
  "created_at": "2026-06-15T10:00:00Z",
  "last_refresh": "2026-06-16T03:00:00Z",
  "quark_user_id": "xxx"
}
```

---

## 6. File Download & Anti-Scraping (Python)

### Download flow

1. Call Quark file-detail API with Cookie → get real download URL
2. Small files: direct download. Large files (>100 MB): chunked with resume support
3. Download to `/tmp/quark_downloads/{task_id}/`
4. Update task status → Node.js reads file → sends to user → Python cleans up (5-min TTL)

### Anti-scraping

| Measure | Detail |
|---------|--------|
| User-Agent pool | Rotate among common browser UAs |
| Referer | Always `https://pan.quark.cn/` |
| Request jitter | 2-5s random interval between requests |
| Download speed cap | Limit to avoid triggering rate control |
| Retry | 3 attempts, exponential backoff |
| Concurrency | Serial queue — only 1 download at a time per account |

### Download task queue

Single serial queue shared across all users. Prevents concurrent downloads from the same Quark account from triggering anti-abuse detection.

---

## 7. Deployment

### Directory structure (on server)

```
~/wechat-quark-bot/
├── node-gateway/          # Node.js message gateway
│   ├── src/
│   ├── package.json
│   └── config/
│       └── bot.json       # iLink bot token
├── python-service/        # Python FastAPI service
│   ├── src/
│   ├── requirements.txt
│   └── config/
│       └── cookies.json   # Quark cookies
├── docker-compose.yml
└── docs/
```

### Process management

`docker-compose.yml` with two services:
- `gateway` — Node.js, port 3000 (internal network)
- `quark-service` — Python, port 8000 (internal network)

Or systemd units: `wechat-gateway.service` + `quark-service.service`.

---

## 8. Future Expansion (out of MVP scope)

- AI essay generation (new Python endpoint)
- Multi-user concurrent browsing
- Multiple cloud storage backends (Baidu, Alibaba)
- Admin dashboard for cookie/health monitoring
