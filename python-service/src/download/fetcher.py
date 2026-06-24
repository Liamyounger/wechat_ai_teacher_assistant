import logging
import random
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) quark-cloud-drive/2.5.56 Chrome/100.0.4896.160 Electron/18.3.5.12-a038f7b798 Safari/537.36 Channel/pckk_other_ch",
]


def download_file(url: str, dest: str, progress_cb=None, max_retries: int = 3,
                  http_client: httpx.Client | None = None) -> str:
    """Download a file with retry and backoff. Returns local path.

    http_client: if provided, reuse this httpx.Client (preserves session cookies
                 needed for Quark CDN callback validation). If None, creates a
                 new client per attempt.
    """
    dest_path = Path(dest)
    last_error = None

    for attempt in range(max_retries):
        ua = random.choice(UA_POOL)
        headers = {
            "user-agent": ua,
            "referer": "https://pan.quark.cn/",
            "origin": "https://pan.quark.cn",
        }

        try:
            if http_client is not None:
                resp = http_client.stream("GET", url, headers=headers)
            else:
                client = httpx.Client(timeout=300.0, follow_redirects=True)
                resp = client.stream("GET", url, headers=headers)

            with resp as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0))
                downloaded = 0
                with open(dest_path, "wb") as f:
                    for chunk in r.iter_bytes(chunk_size=1024 * 1024):
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
            http_client = None  # fall back to fresh client on retry

    raise last_error or RuntimeError("Download failed")
