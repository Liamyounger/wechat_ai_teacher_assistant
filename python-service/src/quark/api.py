import logging
from typing import Any
import httpx
from .cookie import CookieManager

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
                if not entry.get("dir"):
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
