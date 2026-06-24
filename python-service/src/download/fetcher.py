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
                  cookie_dict: dict[str, str] | None = None) -> str:
    """Download a file with retry and backoff. Returns local path."""
    dest_path = Path(dest)
    ua = random.choice(UA_POOL)

    last_error = None
    for attempt in range(max_retries):
        # Try different header strategies across attempts
        header_sets = [
            # Strategy 1: bare minimum — UA only (auth is in URL params)
            {"user-agent": ua},
            # Strategy 2: with referer
            {"user-agent": ua, "referer": "https://pan.quark.cn/"},
            # Strategy 3: full browser-like headers + cookies
            {
                "user-agent": ua,
                "referer": "https://pan.quark.cn/",
                "origin": "https://pan.quark.cn",
                "accept": "*/*",
                "accept-language": "zh-CN,zh;q=0.9",
            },
        ]
        headers = header_sets[min(attempt, len(header_sets) - 1)]

        try:
            client = httpx.Client(timeout=300.0, follow_redirects=True, headers=headers)
            if cookie_dict and attempt >= 2:
                for name, value in cookie_dict.items():
                    client.cookies.set(name, value, domain=".quark.cn")

            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0))
                downloaded = 0
                with open(dest_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0 and progress_cb:
                            progress_cb(int(downloaded * 100 / total))
            client.close()
            return str(dest_path)
        except Exception as e:
            last_error = e
            logger.warning(f"Download attempt {attempt + 1} (strategy {min(attempt, 2) + 1}) failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt + random.uniform(0, 2))

    raise last_error or RuntimeError("Download failed")
