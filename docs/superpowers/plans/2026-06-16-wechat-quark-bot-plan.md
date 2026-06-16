# WeChat Quark Bot — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Linux server app where users navigate Quark cloud folders via WeChat menus and receive PDFs as file messages.

**Architecture:** Node.js gateway (iLink polling + menu sessions) → HTTP REST → Python FastAPI service (Quark API client + download queue). No browser on server — cookies exported once from local PC.

**Tech Stack:** Node.js 24 (native fetch + ESM), Python 3.12+ (FastAPI + httpx), Docker Compose for deployment.

---

## File Map

```
wechat-quark-bot/
├── docker-compose.yml                    # Two-service orchestration
├── deploy.sh                             # One-command deploy
├── python-service/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── config/
│   │   ├── __init__.py
│   │   ├── settings.py                   # Load env / cookie path
│   │   └── cookies.json                  # Manual: from local PC export
│   ├── src/
│   │   ├── __init__.py
│   │   ├── main.py                       # FastAPI app, CORS, lifespan
│   │   ├── quark/
│   │   │   ├── __init__.py
│   │   │   ├── api.py                    # Quark HTTP client (list, download URL)
│   │   │   └── cookie.py                 # Load / refresh / validate cookies
│   │   ├── download/
│   │   │   ├── __init__.py
│   │   │   ├── queue.py                  # In-memory task queue, serial execution
│   │   │   └── fetcher.py               # httpx-based file download with retry
│   │   └── routes.py                     # All API endpoints
│   └── tests/
│       ├── __init__.py
│       ├── test_api.py                   # Quark API client tests
│       └── test_routes.py               # Route integration tests
├── node-gateway/
│   ├── Dockerfile
│   ├── package.json
│   ├── config/
│   │   └── bot.json                      # iLink bot config
│   ├── src/
│   │   ├── index.js                      # Entry: setup or daemon
│   │   ├── logger.js                     # Structured JSON logger
│   │   ├── config.js                     # Config loader
│   │   ├── constants.js                  # Paths, base URLs
│   │   ├── wechat/
│   │   │   ├── api.js                    # iLink API client (WeChatApi class)
│   │   │   ├── types.js                  # Message type enums
│   │   │   ├── sync-buf.js              # Poll cursor persistence
│   │   │   ├── crypto.js                # AES-ECB for file upload
│   │   │   ├── upload.js                # CDN upload + send file
│   │   │   ├── send.js                  # sendText / sendFile helpers
│   │   │   ├── accounts.js             # Load/save bot config
│   │   │   └── monitor.js              # Long-poll loop
│   │   ├── session/
│   │   │   └── manager.js              # Per-user menu session state
│   │   ├── menu/
│   │   │   ├── renderer.js             # Folder → WeChat text menu
│   │   │   └── router.js               # User input → action dispatch
│   │   ├── quark/
│   │   │   └── client.js               # HTTP client to Python service
│   │   └── bot.js                       # Message handler, orchestrator
│   └── tests/
│       └── session.test.js
└── exports/
    └── export_cookies.py                # Local PC: Playwright → cookies.json
```

---

## Phase 1 — Python Service

### Task 1: Scaffold Python project

**Files:**
- Create: `python-service/requirements.txt`
- Create: `python-service/config/__init__.py`
- Create: `python-service/config/settings.py`
- Create: `python-service/src/__init__.py`
- Create: `python-service/src/main.py`

- [ ] **Step 1: Create requirements.txt**

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
httpx==0.28.1
pydantic==2.10.4
pydantic-settings==2.7.1
```

- [ ] **Step 2: Create config/__init__.py**

```python
# config package
```

- [ ] **Step 3: Create config/settings.py**

```python
import json
from pathlib import Path
from pydantic_settings import BaseSettings

CONFIG_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CONFIG_DIR.parent

class Settings(BaseSettings):
    cookies_path: str = str(CONFIG_DIR / "cookies.json")
    download_dir: str = str(Path("/tmp/quark_downloads"))
    download_ttl_seconds: int = 300
    quark_base_url: str = "https://drive-pc.quark.cn"
    log_level: str = "INFO"

    class Config:
        env_prefix = "QUARK_"

settings = Settings()
Path(settings.download_dir).mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: Create src/__init__.py**

```python
# src package
```

- [ ] **Step 5: Create src/main.py**

```python
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from .config.settings import settings as s  # adjusted import
```

Wait — let me fix the import structure. `settings` is in `config/`, `main.py` is in `src/`. So from `src/main.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from config.settings import settings
from src.download.queue import task_queue

logging.basicConfig(level=getattr(logging, settings.log_level.upper()))
logger = logging.getLogger("quark-service")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Quark service starting")
    yield
    task_queue.stop()
    logger.info("Quark service stopped")

app = FastAPI(title="Quark Storage Service", version="0.1.0", lifespan=lifespan)

@app.get("/health")
async def health():
    return {"ok": True}
```

- [ ] **Step 6: Verify it starts**

Run: `cd python-service && python -m uvicorn src.main:app --port 8000`
Expected: `Uvicorn running on http://127.0.0.1:8000`

- [ ] **Step 7: Commit**

---

### Task 2: Cookie manager

**Files:**
- Create: `python-service/src/quark/__init__.py`
- Create: `python-service/src/quark/cookie.py`

- [ ] **Step 1: Create src/quark/__init__.py**

```python
# quark package
```

- [ ] **Step 2: Create src/quark/cookie.py**

```python
import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

class CookieManager:
    def __init__(self, cookies_path: str):
        self.path = Path(cookies_path)
        self._cookies: list[dict[str, Any]] = []
        self._loaded_at: float = 0

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            raise FileNotFoundError(f"Cookie file not found: {self.path}")
        raw = json.loads(self.path.read_text())
        self._cookies = raw.get("cookies", raw if isinstance(raw, list) else [])
        self._loaded_at = time.time()
        logger.info(f"Loaded {len(self._cookies)} cookies from {self.path}")
        return self._cookies

    def to_dict(self) -> dict[str, str]:
        """Return cookies as a {name: value} dict for httpx."""
        if not self._cookies:
            self.load()
        return {c["name"]: c["value"] for c in self._cookies if "name" in c and "value" in c}

    def to_header(self) -> str:
        """Return Cookie header string."""
        pairs = [f"{c['name']}={c['value']}" for c in self._cookies if "name" in c and "value" in c]
        return "; ".join(pairs)

    def is_expired(self) -> bool:
        """Heuristic: cookies older than 7 days likely expired."""
        if not self._cookies:
            return True
        elapsed = time.time() - self._loaded_at
        return elapsed > 7 * 24 * 3600

    def save(self, cookies: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"cookies": cookies, "updated_at": time.time()}
        self.path.write_text(json.dumps(data, indent=2))
        self._cookies = cookies
        self._loaded_at = time.time()
        logger.info(f"Saved {len(cookies)} cookies to {self.path}")
```

- [ ] **Step 3: Commit**

---

### Task 3: Quark API client

**Files:**
- Create: `python-service/src/quark/api.py`

- [ ] **Step 1: Create src/quark/api.py**

The Quark PC drive API uses cookie auth + specific headers. Endpoints discovered from QuarkPanTool / lich0821 QuarkPan:

```python
import logging
from typing import Any
import httpx
from ..cookie import CookieManager

logger = logging.getLogger(__name__)

# Common User-Agent pool
UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]
BASE_URL = "https://drive-pc.quark.cn"

class QuarkClient:
    def __init__(self, cookie_manager: CookieManager):
        self.cookie = cookie_manager
        self._ua_idx = 0
        self.client = httpx.Client(timeout=30.0)

    def _headers(self) -> dict[str, str]:
        ua = UA_POOL[self._ua_idx % len(UA_POOL)]
        self._ua_idx += 1
        return {
            "User-Agent": ua,
            "Referer": "https://pan.quark.cn/",
            "Cookie": self.cookie.to_header(),
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        url = f"{BASE_URL}{path}"
        h = self._headers()
        if "headers" in kwargs:
            h.update(kwargs.pop("headers"))
        resp = self.client.request(method, url, headers=h, **kwargs)
        if resp.status_code == 401:
            raise PermissionError("Quark cookie expired — re-export cookies from local PC")
        resp.raise_for_status()
        return resp.json()

    def list_folder(self, folder_id: str = "0", page: int = 1, size: int = 100) -> dict[str, Any]:
        """List files and subfolders in a given folder.

        folder_id="0" means root. Returns paginated results with 'list' key.
        """
        params = {
            "pr": "pc",
            "pwd": "1",
            "pdir_fid": folder_id,
            "_page": str(page),
            "_size": str(size),
            "_sort": "file_type:asc,updated_at:desc",
        }
        return self._request("GET", "/1/clouddrive/file/sort", params=params)

    def get_file_detail(self, file_id: str) -> dict[str, Any]:
        """Get download URL and file metadata for a specific file."""
        body = {"fids": [file_id]}
        return self._request("POST", "/1/clouddrive/file/download", json=body)

    def get_download_url(self, file_id: str) -> str:
        """Extract the actual download URL from file detail response."""
        detail = self.get_file_detail(file_id)
        data = detail.get("data", [])
        if not data:
            raise ValueError(f"No download info for file {file_id}")
        file_info = data[0]
        download_url = file_info.get("download_url")
        if not download_url:
            raise ValueError(f"No download URL for file {file_id}: {file_info}")
        return download_url

    def resolve_path(self, path: str) -> str:
        """Given a path like /试卷/高二/数学, return the folder_id of the deepest folder.
        Walks the tree one level at a time.
        """
        if path in ("", "/"):
            return "0"
        parts = [p for p in path.strip("/").split("/") if p]
        current_id = "0"
        for name in parts:
            found = self._find_child_folder(current_id, name)
            if found is None:
                raise FileNotFoundError(f"Folder '{name}' not found under id {current_id}")
            current_id = found
        return current_id

    def _find_child_folder(self, parent_id: str, name: str) -> str | None:
        page = 1
        while True:
            resp = self.list_folder(parent_id, page=page, size=100)
            entries = resp.get("data", {}).get("list", [])
            if not entries:
                break
            for entry in entries:
                if entry.get("file") and not entry.get("dir"):  # skip files
                    continue
                if entry.get("file_name") == name:
                    return entry["fid"]
            # Check if there are more pages
            total = resp.get("data", {}).get("total", 0)
            if page * 100 >= total:
                break
            page += 1
        return None

    def close(self):
        self.client.close()
```

- [ ] **Step 2: Commit**

---

### Task 4: Download manager

**Files:**
- Create: `python-service/src/download/__init__.py`
- Create: `python-service/src/download/queue.py`
- Create: `python-service/src/download/fetcher.py`

- [ ] **Step 1: Create src/download/__init__.py**

```python
# download package
```

- [ ] **Step 2: Create src/download/queue.py**

```python
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from config.settings import settings

logger = logging.getLogger(__name__)

class DownloadTask:
    def __init__(self, file_id: str, filename: str):
        self.task_id = uuid.uuid4().hex[:12]
        self.file_id = file_id
        self.filename = filename
        self.status = "queued"       # queued | downloading | done | failed
        self.progress = 0
        self.local_path = ""
        self.error = ""
        self.created_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "progress": self.progress,
            "local_path": self.local_path,
            "error": self.error,
        }

class DownloadQueue:
    def __init__(self):
        self._tasks: dict[str, DownloadTask] = {}
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._worker_thread = threading.Thread(target=self._worker, daemon=True)
        self._running = True
        self._worker_thread.start()

    def submit(self, file_id: str, filename: str) -> DownloadTask:
        task = DownloadTask(file_id, filename)
        with self._lock:
            self._tasks[task.task_id] = task
            self._cv.notify()
        logger.info(f"Download task queued: {task.task_id} ({filename})")
        return task

    def get(self, task_id: str) -> DownloadTask | None:
        with self._lock:
            return self._tasks.get(task_id)

    def _worker(self):
        """Serial download worker — one file at a time to avoid rate limiting."""
        # Lazy import to avoid circular dependency at module load
        from ..quark.api import QuarkClient
        from ..quark.cookie import CookieManager
        from .fetcher import download_file

        cm = CookieManager(settings.cookies_path)
        api = QuarkClient(cm)

        while self._running:
            task = None
            with self._lock:
                for t in self._tasks.values():
                    if t.status == "queued":
                        task = t
                        break
                if task is None:
                    self._cv.wait(timeout=5.0)
                    continue

            try:
                task.status = "downloading"
                task.progress = 0
                logger.info(f"Starting download: {task.filename}")

                download_url = api.get_download_url(task.file_id)
                dest_dir = Path(settings.download_dir) / task.task_id
                dest_dir.mkdir(parents=True, exist_ok=True)

                def progress_cb(pct: int):
                    task.progress = pct

                local = download_file(download_url, str(dest_dir / task.filename),
                                      progress_cb=progress_cb)
                task.local_path = local
                task.progress = 100
                task.status = "done"
                logger.info(f"Download complete: {task.filename}")
            except Exception as e:
                task.status = "failed"
                task.error = str(e)
                logger.error(f"Download failed: {task.filename} — {e}")

        api.close()

    def stop(self):
        self._running = False
        with self._lock:
            self._cv.notify_all()

    def cleanup_old(self):
        """Remove completed/failed tasks older than TTL."""
        cutoff = time.time() - settings.download_ttl_seconds
        with self._lock:
            stale = [
                tid for tid, t in self._tasks.items()
                if t.status in ("done", "failed") and t.created_at < cutoff
            ]
            for tid in stale:
                task = self._tasks.pop(tid)
                # Remove downloaded file
                if task.local_path:
                    try:
                        Path(task.local_path).unlink(missing_ok=True)
                        Path(task.local_path).parent.rmdir()
                    except OSError:
                        pass

task_queue = DownloadQueue()
```

- [ ] **Step 3: Create src/download/fetcher.py**

```python
import logging
import random
import time
from pathlib import Path

logger = logging.getLogger(__name__)

def download_file(url: str, dest: str, progress_cb=None, max_retries: int = 3) -> str:
    """Download a file with retry and backoff. Returns local path."""
    import httpx

    dest_path = Path(dest)
    ua_pool = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    ]

    last_error = None
    for attempt in range(max_retries):
        try:
            headers = {
                "User-Agent": random.choice(ua_pool),
                "Referer": "https://pan.quark.cn/",
            }
            with httpx.stream("GET", url, headers=headers, timeout=300.0,
                              follow_redirects=True) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0))
                downloaded = 0
                with open(dest_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0 and progress_cb:
                            progress_cb(int(downloaded * 100 / total))
            return str(dest_path)
        except Exception as e:
            last_error = e
            logger.warning(f"Download attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt + random.uniform(0, 2))

    raise last_error or RuntimeError("Download failed")
```

- [ ] **Step 4: Commit**

---

### Task 5: API routes

**Files:**
- Create: `python-service/src/routes.py`
- Modify: `python-service/src/main.py` (register routes)

- [ ] **Step 1: Create src/routes.py**

```python
import logging
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .quark.cookie import CookieManager
from .quark.api import QuarkClient
from .download.queue import task_queue
from .config.settings import settings as _s
from config.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")

# Lazy-init globals
_cookie_mgr: CookieManager | None = None
_quark_client: QuarkClient | None = None

def get_quark() -> QuarkClient:
    global _cookie_mgr, _quark_client
    if _quark_client is None:
        _cookie_mgr = CookieManager(settings.cookies_path)
        _quark_client = QuarkClient(_cookie_mgr)
    return _quark_client

class DownloadRequest(BaseModel):
    file_id: str
    filename: str

@router.get("/folder")
async def list_folder(path: str = "/"):
    try:
        api = get_quark()
        folder_id = api.resolve_path(path)
        resp = api.list_folder(folder_id, size=200)
        entries = resp.get("data", {}).get("list", [])

        folders = []
        files = []
        for e in entries:
            is_dir = bool(e.get("dir"))
            name = e.get("file_name", "unknown")
            fid = e.get("fid", "")
            size = e.get("size", 0)

            if is_dir:
                folders.append({"name": name, "fid": fid, "has_children": True})
            else:
                files.append({
                    "name": name,
                    "fid": fid,
                    "size": f"{size / 1024 / 1024:.1f}MB" if size > 1024 * 1024 else f"{size / 1024:.1f}KB",
                })

        return {"path": path, "folders": folders, "files": files}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=401, detail={"error": "cookie_expired", "message": str(e)})
    except Exception as e:
        logger.exception("Folder listing failed")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/download")
async def submit_download(req: DownloadRequest):
    task = task_queue.submit(req.file_id, req.filename)
    return task.to_dict()

@router.get("/download/{task_id}")
async def get_download_status(task_id: str):
    task = task_queue.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.to_dict()
```

- [ ] **Step 2: Modify src/main.py** to register routes

In `src/main.py`, after the app definition, add:
```python
from src.routes import router
app.include_router(router)
```

The updated file should look like:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from config.settings import settings
from src.download.queue import task_queue
from src.routes import router

logging.basicConfig(level=getattr(logging, settings.log_level.upper()))
logger = logging.getLogger("quark-service")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Quark service starting")
    yield
    task_queue.stop()
    logger.info("Quark service stopped")

app = FastAPI(title="Quark Storage Service", version="0.1.0", lifespan=lifespan)
app.include_router(router)

@app.get("/health")
async def health():
    return {"ok": True}
```

- [ ] **Step 3: Commit**

---

### Task 6: Cookie export tool (local PC)

**Files:**
- Create: `exports/export_cookies.py`
- Create: `exports/requirements.txt`

- [ ] **Step 1: Create exports/requirements.txt**

```
playwright==1.49.1
```

- [ ] **Step 2: Create exports/export_cookies.py**

```python
"""Run on local PC with a display. Opens browser, user logs into Quark,
then cookies are exported to cookies.json for upload to the server."""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

OUTPUT = Path(__file__).resolve().parent.parent / "python-service" / "config" / "cookies.json"

def main():
    print("Opening browser for Quark login...")
    with sync_playwright() as p:
        browser = p.firefox.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://pan.quark.cn/")
        print("\nPlease log in to Quark in the browser window.")
        print("After login, press Enter in this terminal to export cookies...")
        input()

        cookies = context.cookies()
        browser.close()

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "cookies": [
            {"name": c["name"], "value": c["value"], "domain": c.get("domain", "")}
            for c in cookies
        ],
        "created_at": __import__("time").time(),
    }
    OUTPUT.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"Cookies exported to {OUTPUT}")
    print("Copy this file to the server: python-service/config/cookies.json")

if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Commit**

---

## Phase 2 — Node.js Gateway

### Task 7: Scaffold Node.js project

**Files:**
- Create: `node-gateway/package.json`
- Create: `node-gateway/config/bot.json`
- Create: `node-gateway/src/constants.js`
- Create: `node-gateway/src/logger.js`

- [ ] **Step 1: Create package.json**

```json
{
  "name": "wechat-quark-gateway",
  "version": "0.1.0",
  "type": "module",
  "private": true,
  "scripts": {
    "setup": "node src/index.js setup",
    "start": "node src/index.js"
  },
  "dependencies": {
    "qrcode": "^1.5.4",
    "qrcode-terminal": "^0.12.0"
  }
}
```

- [ ] **Step 2: Create config/bot.json** (template — user fills in)

```json
{
  "botToken": "YOUR_BOT_TOKEN_HERE",
  "accountId": "YOUR_ACCOUNT_ID@im.bot",
  "baseUrl": "https://ilinkai.weixin.qq.com",
  "quarkServiceUrl": "http://python-service:8000"
}
```

- [ ] **Step 3: Create src/constants.js**

```javascript
import { homedir } from 'node:os';
import { join } from 'node:path';

export const DATA_DIR = process.env.WCC_DATA_DIR || join(homedir(), '.wechat-quark-bot');
export const CDN_BASE_URL = 'https://novac2c.cdn.weixin.qq.com/c2c';
export const CONFIG_PATH = join(DATA_DIR, 'config');
```

- [ ] **Step 4: Create src/logger.js**

```javascript
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
```

- [ ] **Step 5: Commit**

---

### Task 8: WeChat iLink API layer

**Files:**
- Create: `node-gateway/src/wechat/types.js`
- Create: `node-gateway/src/wechat/sync-buf.js`
- Create: `node-gateway/src/wechat/crypto.js`
- Create: `node-gateway/src/wechat/api.js`
- Create: `node-gateway/src/wechat/accounts.js`
- Create: `node-gateway/src/wechat/upload.js`
- Create: `node-gateway/src/wechat/send.js`
- Create: `node-gateway/src/wechat/monitor.js`

These files are adapted directly from the wechat-claude-code reference. Copy them with minimal modifications:

- [ ] **Step 1: Create src/wechat/types.js**

```javascript
export const MessageType = { USER: 1, BOT: 2 };
export const MessageItemType = { TEXT: 1, IMAGE: 2, VOICE: 3, FILE: 4, VIDEO: 5 };
export const MessageState = { NEW: 0, GENERATING: 1, FINISH: 2 };
export const TypingStatus = { TYPING: 1, CANCEL: 2 };
export const UploadMediaType = { IMAGE: 1, VIDEO: 2, FILE: 3, VOICE: 4 };
```

- [ ] **Step 2: Create src/wechat/sync-buf.js**

```javascript
import { join } from 'node:path';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { DATA_DIR } from '../constants.js';

const BUF_PATH = join(DATA_DIR, 'get_updates_buf');

export function loadSyncBuf() {
    try { return readFileSync(BUF_PATH, 'utf-8').trim(); }
    catch { return ''; }
}

export function saveSyncBuf(buf) {
    mkdirSync(DATA_DIR, { recursive: true });
    writeFileSync(BUF_PATH, buf, 'utf-8');
}
```

- [ ] **Step 3: Create src/wechat/crypto.js**

```javascript
import { createCipheriv } from 'node:crypto';

export function aesEcbPaddedSize(plainSize) {
    const blockSize = 16;
    return plainSize + blockSize - (plainSize % blockSize);
}

export function encryptAesEcb(key, plaintext) {
    const cipher = createCipheriv('aes-128-ecb', key, null);
    return Buffer.concat([cipher.update(plaintext), cipher.final()]);
}
```

- [ ] **Step 4: Create src/wechat/api.js**

```javascript
import { logger } from '../logger.js';

function generateUin() {
    const buf = new Uint8Array(4);
    crypto.getRandomValues(buf);
    return Buffer.from(buf).toString('base64');
}

export class WeChatApi {
    constructor(token, baseUrl = 'https://ilinkai.weixin.qq.com') {
        this.token = token;
        this.baseUrl = baseUrl.replace(/\/+$/, '');
        this.uin = generateUin();
        this.nextSendTime = new Map();
    }

    static MIN_SEND_INTERVAL = 2500;

    headers() {
        return {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${this.token}`,
            'AuthorizationType': 'ilink_bot_token',
            'X-WECHAT-UIN': this.uin,
        };
    }

    async request(path, body, timeoutMs = 15_000) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeoutMs);
        const url = `${this.baseUrl}/${path}`;
        logger.debug('API request', { url, body });
        try {
            const res = await fetch(url, {
                method: 'POST',
                headers: this.headers(),
                body: JSON.stringify(body),
                signal: controller.signal,
            });
            if (!res.ok) {
                const text = await res.text();
                throw new Error(`HTTP ${res.status}: ${text}`);
            }
            const json = await res.json();
            logger.debug('API response', json);
            return json;
        } finally {
            clearTimeout(timer);
        }
    }

    async getUpdates(buf) {
        return this.request('ilink/bot/getupdates', buf ? { get_updates_buf: buf } : {}, 35_000);
    }

    async sendMessage(req) {
        const userId = req.msg?.to_user_id;
        if (userId) {
            const now = Date.now();
            const nextAvailable = (this.nextSendTime.get(userId) ?? 0) + WeChatApi.MIN_SEND_INTERVAL;
            const sendAt = Math.max(now, nextAvailable);
            this.nextSendTime.set(userId, sendAt);
            const waitMs = sendAt - now;
            if (waitMs > 0) await new Promise(r => setTimeout(r, waitMs));
        }
        const MAX_RETRIES = 2;
        let delay = 3_000;
        for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
            const res = await this.request('ilink/bot/sendmessage', req);
            if (res.ret === -2) {
                if (userId) this.nextSendTime.set(userId, Date.now() + delay + WeChatApi.MIN_SEND_INTERVAL);
                if (attempt === MAX_RETRIES) {
                    throw new Error(`sendMessage rate-limited after ${MAX_RETRIES} retries`);
                }
                logger.warn('sendMessage rate-limited, retrying', { attempt, delayMs: delay });
                await new Promise(r => setTimeout(r, delay));
                delay = Math.min(delay * 2, 15_000);
                continue;
            }
            return;
        }
    }

    async getConfig(ilinkUserId, contextToken) {
        return this.request('ilink/bot/getconfig', { ilink_user_id: ilinkUserId, context_token: contextToken }, 10_000);
    }

    async sendTyping(req) {
        await this.request('ilink/bot/sendtyping', req, 10_000);
    }

    async getUploadUrl(req) {
        return this.request('ilink/bot/getuploadurl', req);
    }
}
```

- [ ] **Step 5: Create src/wechat/accounts.js**

```javascript
import { join } from 'node:path';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { DATA_DIR } from '../constants.js';

const ACCOUNTS_DIR = join(DATA_DIR, 'accounts');

export function saveAccount(data) {
    mkdirSync(ACCOUNTS_DIR, { recursive: true });
    writeFileSync(join(ACCOUNTS_DIR, `${data.accountId}.json`), JSON.stringify(data, null, 2));
}

export function loadAccount(accountId) {
    try {
        return JSON.parse(readFileSync(join(ACCOUNTS_DIR, `${accountId}.json`), 'utf-8'));
    } catch { return null; }
}

export function loadConfig() {
    try {
        return JSON.parse(readFileSync(join(DATA_DIR, 'config', 'bot.json'), 'utf-8'));
    } catch { return null; }
}
```

- [ ] **Step 6: Create src/wechat/upload.js**

```javascript
import { createHash, randomBytes } from 'node:crypto';
import { readFileSync, statSync } from 'node:fs';
import { basename, extname } from 'node:path';
import { encryptAesEcb, aesEcbPaddedSize } from './crypto.js';
import { UploadMediaType } from './types.js';
import { CDN_BASE_URL } from '../constants.js';
import { logger } from '../logger.js';

const MAX_FILE_SIZE = 25 * 1024 * 1024;
const IMAGE_EXTS = new Set(['.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.svg', '.ico']);

function isImageFile(fp) { return IMAGE_EXTS.has(extname(fp).toLowerCase()); }

export async function uploadFile(api, toUserId, filePath) {
    const stat = statSync(filePath);
    if (stat.size > MAX_FILE_SIZE) {
        throw new Error(`File too large (${(stat.size / 1024 / 1024).toFixed(1)}MB), max 25MB`);
    }
    const fileName = basename(filePath);
    const isImage = isImageFile(filePath);
    const mediaType = isImage ? UploadMediaType.IMAGE : UploadMediaType.FILE;
    const plaintext = readFileSync(filePath);
    const rawSize = plaintext.length;
    const rawFileMd5 = createHash('md5').update(plaintext).digest('hex');
    const fileSize = aesEcbPaddedSize(rawSize);
    const fileKey = randomBytes(16).toString('hex');
    const aesKey = randomBytes(16);
    const aesKeyHex = aesKey.toString('hex');

    const uploadResp = await api.getUploadUrl({
        filekey: fileKey, media_type: mediaType, to_user_id: toUserId,
        rawsize: rawSize, rawfilemd5: rawFileMd5, filesize: fileSize,
        no_need_thumb: true, aeskey: aesKeyHex,
        base_info: { channel_version: '2.0.0', bot_agent: 'wechat-quark-bot' },
    });
    if (!uploadResp.upload_full_url && !uploadResp.upload_param) {
        throw new Error(`Upload URL error: ${JSON.stringify(uploadResp)}`);
    }

    const encrypted = encryptAesEcb(aesKey, plaintext);
    let uploadUrl = uploadResp.upload_full_url
        || `${CDN_BASE_URL}/upload?encrypted_query_param=${encodeURIComponent(uploadResp.upload_param)}&filekey=${fileKey}`;

    logger.info('Uploading to CDN', { fileName, encryptedSize: encrypted.length });
    const encryptQueryParam = await uploadToCdn(uploadUrl, encrypted);
    return {
        mediaType: isImage ? 'image' : 'file',
        encryptQueryParam, aesKeyHex, fileName, fileSize, rawSize,
    };
}

async function uploadToCdn(url, encrypted) {
    for (let attempt = 0; attempt < 3; attempt++) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 60_000);
        try {
            const res = await fetch(url, {
                method: 'POST', body: new Uint8Array(encrypted),
                signal: controller.signal,
                headers: { 'Content-Type': 'application/octet-stream' },
            });
            if (res.status >= 500) { logger.warn('CDN 5xx, retrying', { attempt }); continue; }
            if (!res.ok) {
                const text = await res.text();
                throw new Error(`CDN upload failed: ${res.status} ${text.slice(0, 200)}`);
            }
            const param = res.headers.get('x-encrypted-param');
            if (!param) throw new Error('CDN upload missing x-encrypted-param');
            return param;
        } finally { clearTimeout(timer); }
    }
    throw new Error('CDN upload failed after retries');
}
```

- [ ] **Step 7: Create src/wechat/send.js**

```javascript
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { homedir } from 'node:os';
import { MessageItemType, MessageType, MessageState, TypingStatus } from './types.js';
import { uploadFile } from './upload.js';
import { logger } from '../logger.js';

export function createSender(api, botAccountId) {
    let counter = 0;
    const ticketCache = new Map();

    function genClientId() { return `wqb-${Date.now()}-${++counter}`; }

    async function getTypingTicket(userId, contextToken) {
        const cached = ticketCache.get(userId);
        if (cached && Date.now() - cached.at < 24 * 60 * 60 * 1000) return cached.ticket;
        try {
            const resp = await api.getConfig(userId, contextToken);
            if (resp.ret === 0 && resp.typing_ticket) {
                ticketCache.set(userId, { ticket: resp.typing_ticket, at: Date.now() });
                return resp.typing_ticket;
            }
        } catch (err) { logger.warn('getConfig failed', { err: err.message }); }
        return '';
    }

    function startTyping(toUserId, contextToken) {
        let cancelled = false;
        (async () => {
            const ticket = await getTypingTicket(toUserId, contextToken);
            if (!ticket || cancelled) return;
            try { await api.sendTyping({ ilink_user_id: toUserId, typing_ticket: ticket, status: TypingStatus.TYPING }); }
            catch { return; }
            while (!cancelled) {
                await new Promise(r => setTimeout(r, 5_000));
                if (cancelled) break;
                try { await api.sendTyping({ ilink_user_id: toUserId, typing_ticket: ticket, status: TypingStatus.TYPING }); }
                catch { break; }
            }
            try { await api.sendTyping({ ilink_user_id: toUserId, typing_ticket: ticket, status: TypingStatus.CANCEL }); }
            catch { /* ignore */ }
        })();
        return () => { cancelled = true; };
    }

    async function sendText(toUserId, contextToken, text) {
        const clientId = genClientId();
        const msg = {
            from_user_id: botAccountId,
            to_user_id: toUserId,
            client_id: clientId,
            message_type: MessageType.BOT,
            message_state: MessageState.FINISH,
            context_token: contextToken,
            item_list: [{ type: MessageItemType.TEXT, text_item: { text } }],
        };
        await api.sendMessage({ msg });
    }

    async function sendFile(toUserId, contextToken, filePath) {
        const resolved = resolve(filePath.replace(/^~/, homedir()));
        if (!existsSync(resolved)) {
            await sendText(toUserId, contextToken, `文件不存在: ${resolved}`);
            return;
        }
        const media = await uploadFile(api, toUserId, resolved);
        const aesKeyBase64 = Buffer.from(media.aesKeyHex).toString('base64');
        const item = media.mediaType === 'image' ? {
            type: MessageItemType.IMAGE,
            image_item: {
                media: { encrypt_query_param: media.encryptQueryParam, aes_key: aesKeyBase64, encrypt_type: 1 },
                mid_size: media.fileSize,
            },
        } : {
            type: MessageItemType.FILE,
            file_item: {
                media: { encrypt_query_param: media.encryptQueryParam, aes_key: aesKeyBase64, encrypt_type: 1 },
                file_name: media.fileName,
                len: String(media.rawSize),
            },
        };
        const msg = {
            from_user_id: botAccountId,
            to_user_id: toUserId,
            client_id: genClientId(),
            message_type: MessageType.BOT,
            message_state: MessageState.FINISH,
            context_token: contextToken,
            item_list: [item],
        };
        await api.sendMessage({ msg });
    }

    return { sendText, startTyping, sendFile };
}
```

- [ ] **Step 8: Create src/wechat/monitor.js**

```javascript
import { loadSyncBuf, saveSyncBuf } from './sync-buf.js';
import { logger } from '../logger.js';

const SESSION_EXPIRED_ERRCODE = -14;
const SESSION_EXPIRED_PAUSE = 60 * 60 * 1000;

export function createMonitor(api, callbacks) {
    const controller = new AbortController();
    const recentMsgIds = new Set();

    async function run() {
        let failures = 0;
        while (!controller.signal.aborted) {
            try {
                const buf = loadSyncBuf();
                const resp = await api.getUpdates(buf || undefined);
                if (resp.ret === SESSION_EXPIRED_ERRCODE) {
                    logger.warn('Session expired, pausing 1hr');
                    callbacks.onSessionExpired?.();
                    await sleep(SESSION_EXPIRED_PAUSE, controller.signal);
                    failures = 0;
                    continue;
                }
                if (resp.get_updates_buf) saveSyncBuf(resp.get_updates_buf);
                const msgs = resp.msgs ?? [];
                if (msgs.length > 0) {
                    logger.info('Received messages', { count: msgs.length });
                    for (const msg of msgs) {
                        if (msg.message_id && recentMsgIds.has(msg.message_id)) continue;
                        if (msg.message_id) {
                            recentMsgIds.add(msg.message_id);
                            if (recentMsgIds.size > 1000) {
                                const iter = recentMsgIds.values();
                                for (let i = 0; i < 500; i++) recentMsgIds.delete(iter.next().value);
                            }
                        }
                        callbacks.onMessage(msg).catch(err =>
                            logger.error('Error processing message', { error: err.message }));
                    }
                }
                failures = 0;
            } catch (err) {
                if (controller.signal.aborted) break;
                failures++;
                const backoff = failures >= 3 ? 30_000 : 3_000;
                logger.error('Monitor error', { error: err.message, failures });
                await sleep(backoff, controller.signal);
            }
        }
        logger.info('Monitor stopped');
    }

    function stop() { controller.abort(); }
    return { run, stop };
}

function sleep(ms, signal) {
    return new Promise(resolve => {
        if (signal?.aborted) { resolve(); return; }
        const timer = setTimeout(resolve, ms);
        signal?.addEventListener('abort', () => { clearTimeout(timer); resolve(); }, { once: true });
    });
}
```

- [ ] **Step 9: Commit**

---

### Task 9: Session manager

**Files:**
- Create: `node-gateway/src/session/manager.js`

- [ ] **Step 1: Create src/session/manager.js**

```javascript
import { logger } from '../logger.js';

const SESSION_TTL_MS = 30 * 60 * 1000; // 30 minutes

/**
 * @typedef {Object} UserSession
 * @property {string} userId
 * @property {string} currentPath - e.g. "/试卷/高二"
 * @property {'idle'|'browsing'|'awaiting_download_confirm'} state
 * @property {{fid: string, filename: string}|null} selectedFile
 * @property {number} lastActivity - Date.now()
 */

export function createSessionManager() {
    /** @type {Map<string, UserSession>} */
    const sessions = new Map();

    function get(userId) {
        const s = sessions.get(userId);
        if (!s) return null;
        if (Date.now() - s.lastActivity > SESSION_TTL_MS) {
            sessions.delete(userId);
            return null;
        }
        return s;
    }

    function getOrCreate(userId) {
        let s = get(userId);
        if (!s) {
            s = {
                userId,
                currentPath: '/试卷',
                state: 'browsing',
                selectedFile: null,
                lastActivity: Date.now(),
            };
            sessions.set(userId, s);
        }
        s.lastActivity = Date.now();
        return s;
    }

    function update(userId, partial) {
        const s = getOrCreate(userId);
        Object.assign(s, partial, { lastActivity: Date.now() });
        return s;
    }

    function reset(userId) {
        sessions.delete(userId);
        return getOrCreate(userId);
    }

    // Periodic cleanup
    setInterval(() => {
        const now = Date.now();
        for (const [id, s] of sessions) {
            if (now - s.lastActivity > SESSION_TTL_MS) {
                sessions.delete(id);
                logger.debug('Session expired', { userId: id });
            }
        }
    }, 60_000);

    return { get, getOrCreate, update, reset };
}
```

- [ ] **Step 2: Commit**

---

### Task 10: Menu renderer and router

**Files:**
- Create: `node-gateway/src/menu/renderer.js`
- Create: `node-gateway/src/menu/router.js`

- [ ] **Step 1: Create src/menu/renderer.js**

```javascript
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
```

- [ ] **Step 2: Create src/menu/router.js**

```javascript
import { getItems } from './renderer.js';

/**
 * Parse user text input and determine the action.
 *
 * @param {string} text - User's message text
 * @param {Object} folderData - Response from GET /api/v1/folder
 * @param {string} currentPath - Current folder path
 * @param {number} currentPage - Current page index
 * @returns {{
 *   action: 'navigate'|'select_file'|'back'|'prev_page'|'next_page'|'reset'|'invalid'|'browse_root',
 *   targetPath?: string,
 *   selectedFile?: {fid: string, filename: string},
 *   page?: number,
 *   message?: string,
 * }}
 */
export function routeInput(text, folderData, currentPath, currentPage) {
    const input = text.trim().toLowerCase();

    if (input === '0' || input === '返回' || input === 'back') {
        if (currentPath === '/' || currentPath === '/试卷') {
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
```

- [ ] **Step 3: Commit**

---

### Task 11: Quark HTTP client (Node.js → Python)

**Files:**
- Create: `node-gateway/src/quark/client.js`

- [ ] **Step 1: Create src/quark/client.js**

```javascript
import { logger } from '../logger.js';

export class QuarkServiceClient {
    constructor(baseUrl = 'http://127.0.0.1:8000') {
        this.baseUrl = baseUrl.replace(/\/+$/, '');
    }

    async request(path) {
        const url = `${this.baseUrl}${path}`;
        logger.debug('Quark service request', { url });
        const res = await fetch(url, { signal: AbortSignal.timeout(15_000) });
        const body = await res.json();
        if (!res.ok) {
            const err = new Error(body.detail || body.message || `HTTP ${res.status}`);
            err.status = res.status;
            err.body = body;
            throw err;
        }
        return body;
    }

    /** GET /api/v1/folder?path=/试卷/高二 */
    async listFolder(path) {
        return this.request(`/api/v1/folder?path=${encodeURIComponent(path)}`);
    }

    /** POST /api/v1/download */
    async submitDownload(fileId, filename) {
        const url = `${this.baseUrl}/api/v1/download`;
        const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ file_id: fileId, filename }),
            signal: AbortSignal.timeout(10_000),
        });
        return res.json();
    }

    /** GET /api/v1/download/{task_id} */
    async getDownloadStatus(taskId) {
        return this.request(`/api/v1/download/${taskId}`);
    }

    /** Poll until download completes or fails. */
    async waitForDownload(taskId, pollMs = 1500, maxWaitMs = 300_000) {
        const start = Date.now();
        while (Date.now() - start < maxWaitMs) {
            const status = await this.getDownloadStatus(taskId);
            if (status.status === 'done') return status;
            if (status.status === 'failed') throw new Error(status.error || 'Download failed');
            await new Promise(r => setTimeout(r, pollMs));
        }
        throw new Error('Download timed out');
    }
}
```

- [ ] **Step 2: Commit**

---

### Task 12: Main bot handler

**Files:**
- Create: `node-gateway/src/bot.js`
- Create: `node-gateway/src/index.js`

- [ ] **Step 1: Create src/bot.js**

```javascript
import { MessageType } from './wechat/types.js';
import { createSender } from './wechat/send.js';
import { renderMenu } from './menu/renderer.js';
import { routeInput } from './menu/router.js';
import { QuarkServiceClient } from './quark/client.js';
import { logger } from './logger.js';

/**
 * Create the message handler. Returns a function that processes one WeChat message.
 */
export function createHandler(sessionManager, quarkClient, sender) {

    /**
     * @param {Object} msg - iLink message object
     * @param {string} contextToken
     */
    return async function handleMessage(msg, contextToken) {
        if (msg.message_type !== MessageType.USER) return;
        if (!msg.from_user_id || !msg.item_list) return;

        const userId = msg.from_user_id;
        const text = extractText(msg.item_list);
        const session = sessionManager.getOrCreate(userId);

        // Handle download confirmation
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
                session.currentPath = '/试卷';
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

async function handleDownload(userId, contextToken, session, quarkClient, sender) {
    const { fid, filename } = session.selectedFile;
    session.state = 'browsing';
    session.selectedFile = null;

    try {
        await sender.sendText(userId, contextToken, `⏳ 正在下载 「${filename}」...`);
        const task = await quarkClient.submitDownload(fid, filename);
        const result = await quarkClient.waitForDownload(task.task_id);
        await sender.sendFile(userId, contextToken, result.local_path);
        await sender.sendText(userId, contextToken,
            `✅ 「${filename}」发送完成！继续浏览：`);
    } catch (err) {
        logger.error('Download failed', { error: err.message });
        await sender.sendText(userId, contextToken, `下载失败: ${err.message}`);
    }

    // Show menu again
    await showCurrentFolder(userId, contextToken, session, quarkClient, sender);
}

function extractText(items) {
    return items
        .filter(i => i.type === 1 && i.text_item)
        .map(i => i.text_item.text)
        .join('\n');
}
```

- [ ] **Step 2: Create src/index.js**

```javascript
import process from 'node:process';
import { mkdirSync } from 'node:fs';
import { WeChatApi } from './wechat/api.js';
import { loadAccount, loadConfig } from './wechat/accounts.js';
import { createMonitor } from './wechat/monitor.js';
import { createSender } from './wechat/send.js';
import { createSessionManager } from './session/manager.js';
import { createHandler } from './bot.js';
import { QuarkServiceClient } from './quark/client.js';
import { DATA_DIR } from './constants.js';
import { logger } from './logger.js';

async function runDaemon() {
    const botConfig = loadConfig();
    if (!botConfig?.botToken || botConfig.botToken === 'YOUR_BOT_TOKEN_HERE') {
        console.error('Please configure config/bot.json with your bot token');
        process.exit(1);
    }

    const account = { accountId: botConfig.accountId, botToken: botConfig.botToken, baseUrl: botConfig.baseUrl };
    const api = new WeChatApi(account.botToken, account.baseUrl);
    const sender = createSender(api, account.accountId);
    const sessionManager = createSessionManager();
    const quarkClient = new QuarkServiceClient(botConfig.quarkServiceUrl || 'http://127.0.0.1:8000');
    const handleMessage = createHandler(sessionManager, quarkClient, sender);

    const sharedCtx = { lastContextToken: '' };
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
            sharedCtx.lastContextToken = ctx;
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
    // Setup: user manually creates config/bot.json with their token
    console.log('Setup: Edit config/bot.json with your bot token, then run "npm start"');
    process.exit(0);
} else {
    runDaemon().catch(err => {
        logger.error('Fatal', { error: err.message });
        console.error('Fatal error:', err);
        process.exit(1);
    });
}
```

- [ ] **Step 3: Commit**

---

## Phase 3 — Integration & Deployment

### Task 13: Docker Compose

**Files:**
- Create: `docker-compose.yml`
- Create: `python-service/Dockerfile`
- Create: `node-gateway/Dockerfile`

- [ ] **Step 1: Create python-service/Dockerfile**

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

RUN mkdir -p /tmp/quark_downloads

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Create node-gateway/Dockerfile**

```dockerfile
FROM node:24-alpine

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --production
COPY . .

RUN mkdir -p /root/.wechat-quark-bot

CMD ["node", "src/index.js"]
```

- [ ] **Step 3: Create docker-compose.yml**

```yaml
version: "3.8"
services:
  python-service:
    build: ./python-service
    container_name: quark-service
    volumes:
      - ./python-service/config/cookies.json:/app/config/cookies.json:ro
      - quark_downloads:/tmp/quark_downloads
    restart: unless-stopped
    environment:
      - QUARK_LOG_LEVEL=INFO

  node-gateway:
    build: ./node-gateway
    container_name: wechat-gateway
    volumes:
      - ./node-gateway/config/bot.json:/app/config/bot.json:ro
      - gateway_data:/root/.wechat-quark-bot
      - quark_downloads:/tmp/quark_downloads:ro
    restart: unless-stopped
    environment:
      - LOG_LEVEL=INFO
    depends_on:
      - python-service

volumes:
  quark_downloads:
  gateway_data:
```

- [ ] **Step 4: Commit**

---

### Task 14: Deployment script

**Files:**
- Create: `deploy.sh`

- [ ] **Step 1: Create deploy.sh**

```bash
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
```

- [ ] **Step 2: Make deploy.sh executable**

Run: `chmod +x deploy.sh`

- [ ] **Step 3: Commit**

---

### Task 15: End-to-end smoke test

- [ ] **Step 1: Start Python service locally**

Run: `cd python-service && pip install -r requirements.txt && python -m uvicorn src.main:app --port 8000`

- [ ] **Step 2: Test health endpoint**

Run: `curl http://localhost:8000/health`
Expected: `{"ok":true}`

- [ ] **Step 3: Verify folder listing (with valid cookies.json)**

Run: `curl "http://localhost:8000/api/v1/folder?path=/试卷"`
Expected: JSON with folders and files arrays, or 401 if cookies invalid.

- [ ] **Step 4: Start Node.js gateway**

Run: `cd node-gateway && npm install && node src/index.js`
Expected: `WeChat Quark Bot started (account: xxx)`

- [ ] **Step 5: Send test WeChat message**

Open WeChat, send any text to the bot.
Expected: Menu with folder listing returned.

- [ ] **Step 6: Navigate and download**

Send "1" to enter first folder, navigate to a PDF, confirm with "y".
Expected: File delivered in WeChat.

- [ ] **Step 7: Commit**
