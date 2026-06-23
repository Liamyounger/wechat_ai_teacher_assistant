import logging
import time
import httpx
from typing import Any

logger = logging.getLogger(__name__)

BASE_URL = "https://drive-pc.quark.cn/1/clouddrive"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36"
    " (KHTML, like Gecko) Chrome/94.0.4606.71 Safari/537.36"
    " Core/1.94.225.400 QQBrowser/12.2.5544.400"
)

DEFAULT_PARAMS = {"pr": "ucpro", "fr": "pc", "uc_param_str": ""}


class QuarkShareClient:
    """Access a Quark shared folder: list contents and get download info."""

    def __init__(self, cookie_manager=None):
        self.cookie = cookie_manager  # optional CookieManager for auth
        self.client = httpx.Client(timeout=60.0, follow_redirects=True)
        self._stoken_cache: dict[str, str] = {}

    def _headers(self) -> dict[str, str]:
        h = {
            "User-Agent": UA,
            "Origin": "https://pan.quark.cn",
            "Referer": "https://pan.quark.cn/",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
        }
        if self.cookie:
            h["Cookie"] = self.cookie.to_header()
        return h

    def _params(self, **extra) -> dict[str, Any]:
        p = DEFAULT_PARAMS.copy()
        p["__t"] = int(time.time() * 1000)
        p["__dt"] = 1000
        p.update(extra)
        return p

    def _get_stoken(self, share_id: str, passcode: str = "") -> str:
        if share_id in self._stoken_cache:
            return self._stoken_cache[share_id]

        resp = self.client.post(
            f"{BASE_URL}/share/sharepage/token",
            params=self._params(),
            headers=self._headers(),
            json={"pwd_id": share_id, "passcode": passcode},
        )
        data = resp.json()
        if data.get("status") != 200:
            raise PermissionError(f"Share access failed: {data.get('message', 'unknown')}")
        stoken = data["data"]["stoken"]
        self._stoken_cache[share_id] = stoken
        return stoken

    def list_share_folder(self, share_id: str, pdir_fid: str = "0",
                          page: int = 1, size: int = 100) -> dict[str, Any]:
        """List files/folders in a shared folder."""
        stoken = self._get_stoken(share_id)
        resp = self.client.get(
            f"{BASE_URL}/share/sharepage/detail",
            params=self._params(
                _st="none",
                pwd_id=share_id,
                stoken=stoken,
                pdir_fid=pdir_fid,
                force="0",
                _page=str(page),
                _size=str(size),
                _sort="file_type:asc,updated_at:desc",
            ),
            headers=self._headers(),
        )
        data = resp.json()
        if data.get("status") != 200:
            raise RuntimeError(f"Share listing failed: {data.get('message', '')}")
        return data.get("data", {})

    def get_share_files(self, share_id: str, pdir_fid: str = "0") -> list[dict]:
        """Get all files (not folders) in a shared location (non-recursive)."""
        data = self.list_share_folder(share_id, pdir_fid)
        entries = data.get("list", [])

        folders = []
        files = []
        for e in entries:
            entry = {
                "name": e.get("file_name", "unknown"),
                "fid": e.get("fid", ""),
                "size": e.get("size", 0),
                "is_dir": bool(e.get("dir")),
            }
            if entry["is_dir"]:
                folders.append(entry)
            else:
                entry["size_display"] = (
                    f"{entry['size'] / 1024 / 1024:.1f}MB"
                    if entry["size"] > 1024 * 1024
                    else f"{entry['size'] / 1024:.1f}KB"
                )
                files.append(entry)

        return {"folders": folders, "files": files,
                "total": data.get("total", len(entries))}

    def get_download_url(self, share_id: str, fid: str) -> tuple[str, str]:
        """Get download URL and filename for a file in a share."""
        stoken = self._get_stoken(share_id)

        # Use the regular file detail endpoint with share params
        resp = self.client.get(
            f"{BASE_URL}/file",
            params=self._params(
                fids=fid,
                pwd_id=share_id,
                stoken=stoken,
            ),
            headers=self._headers(),
        )
        data = resp.json()
        file_list = data.get("data", [])
        if not file_list:
            raise ValueError(f"File {fid} not found in share {share_id}")

        info = file_list[0]
        dl_url = info.get("download_url")
        if not dl_url:
            raise ValueError(f"No download URL for file {fid}: {info}")

        return dl_url, info.get("file_name", "unknown")

    def close(self):
        self.client.close()


def extract_share_id(url: str) -> str | None:
    """Extract share_id from a Quark share URL like pan.quark.cn/s/xxxxx."""
    import re
    match = re.search(r'pan\.quark\.cn/s/([a-zA-Z0-9]+)', url)
    return match.group(1) if match else None
