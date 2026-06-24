import logging
import random
import time
from pathlib import Path

logger = logging.getLogger(__name__)

def download_file(url: str, dest: str, progress_cb=None, max_retries: int = 3, cookies: str = "") -> str:
    """Download a file with retry and backoff. Returns local path."""
    import httpx

    dest_path = Path(dest)
    ua_pool = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) quark-cloud-drive/2.5.56 Chrome/100.0.4896.160 Electron/18.3.5.12-a038f7b798 Safari/537.36 Channel/pckk_other_ch",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    ]

    last_error = None
    for attempt in range(max_retries):
        try:
            headers = {
                "User-Agent": random.choice(ua_pool),
                "Referer": "https://pan.quark.cn/",
                "Origin": "https://pan.quark.cn",
            }
            if cookies:
                headers["Cookie"] = cookies
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
