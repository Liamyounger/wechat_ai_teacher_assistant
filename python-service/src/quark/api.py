import logging
import time
from typing import Any
import httpx
from .cookie import CookieManager

logger = logging.getLogger(__name__)

BASE_URL = "https://drive-pc.quark.cn/1/clouddrive"

# Default params included with every request (matches quarkpan)
DEFAULT_PARAMS = {
    "pr": "ucpro",
    "fr": "pc",
    "uc_param_str": "",
}

UA = (
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36"
    " (KHTML, like Gecko) Chrome/94.0.4606.71 Safari/537.36"
    " Core/1.94.225.400 QQBrowser/12.2.5544.400"
)


class QuarkClient:
    def __init__(self, cookie_manager: CookieManager):
        self.cookie = cookie_manager
        self.client = httpx.Client(timeout=60.0, follow_redirects=True)

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": UA,
            "Origin": "https://pan.quark.cn",
            "Referer": "https://pan.quark.cn/",
            "Cookie": self.cookie.to_header(),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Content-Type": "application/json",
        }

    def _params(self, **extra) -> dict[str, Any]:
        p = DEFAULT_PARAMS.copy()
        p["__t"] = int(time.time() * 1000)
        p["__dt"] = 1000
        p.update(extra)
        return p

    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        url = f"{BASE_URL}/{path.lstrip('/')}"
        h = self._headers()
        if "headers" in kwargs:
            h.update(kwargs.pop("headers"))
        # Merge default params with request params
        req_params = kwargs.pop("params", {})
        kwargs["params"] = self._params(**req_params)
        resp = self.client.request(method, url, headers=h, **kwargs)
        if resp.status_code == 401:
            raise PermissionError("Quark cookie expired — re-run quark_setup.py on server")
        resp.raise_for_status()
        return resp.json()

    def list_folder(self, folder_id: str = "0", page: int = 1, size: int = 100) -> dict[str, Any]:
        return self._request("GET", "file/sort", params={
            "pdir_fid": folder_id,
            "_page": str(page),
            "_size": str(size),
            "_sort": "file_name:asc",
        })

    def get_file_detail(self, file_id: str) -> dict[str, Any]:
        return self._request("GET", "file", params={"fids": file_id})

    def get_download_url(self, file_id: str) -> str:
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
            total = resp.get("data", {}).get("total", 0)
            if page * 100 >= total:
                break
            page += 1
        return None

    def close(self):
        self.client.close()
