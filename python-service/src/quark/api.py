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

    def get_download_url(self, file_id: str) -> tuple[str, str]:
        """Get download URL and filename via POST /file/download (correct Quark API).
        Returns (download_url, filename)."""
        resp = self._request("POST", "file/download", json={"fids": [file_id]},
                             params={"sys": "win32", "ve": "2.5.56"})
        data = resp.get("data", [])
        if not data:
            raise ValueError(f"No download info for file {file_id}")
        info = data[0]
        url = info.get("download_url")
        if not url:
            raise ValueError(f"No download URL for file {file_id}: {info}")
        return url, info.get("file_name", "unknown")

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

    # ── File operations ──────────────────────────────────────────────

    def create_folder(self, parent_fid: str, name: str) -> str:
        """Create a folder and return its fid."""
        resp = self._request("POST", "file", json={
            "pdir_fid": parent_fid,
            "file_name": name,
            "dir": True,
        })
        return resp["data"]["fid"]

    def rename_file(self, fid: str, new_name: str) -> None:
        self._request("POST", "file/rename", json={
            "fid": fid,
            "file_name": new_name,
        })

    def move_files(self, parent_fid: str, filelist: list[str], dest_fid: str) -> None:
        """Move files to a destination folder. parent_fid is the source folder."""
        self._request("POST", "file/move", json={
            "current_dir_fid": parent_fid,
            "filelist": filelist,
            "to_pdir_fid": dest_fid,
        })

    def delete_files(self, parent_fid: str, filelist: list[str]) -> None:
        self._request("POST", "file/delete", json={
            "current_dir_fid": parent_fid,
            "filelist": filelist,
        })

    def create_share_url(self, fid: str, filename: str, expired_type: int = 1) -> str:
        """Create a share link for a file. expired_type: 1=permanent, 2=1d, 3=7d, 4=30d.
        Returns the share URL."""
        # Step 1: create share task
        task_resp = self._request("POST", "share", json={
            "fid_list": [fid],
            "title": filename,
            "url_type": 1,
            "expired_type": expired_type,
        })
        task_id = task_resp["data"]["task_id"]

        # Step 2: get share_id from task
        task_info = self._request("GET", "task", params={
            "task_id": task_id,
            "retry_index": "0",
        })
        share_id = task_info["data"]["share_id"]

        # Step 3: submit share to get URL
        share_resp = self._request("POST", "share/password", json={
            "share_id": share_id,
        })
        return share_resp["data"]["share_url"]

    def search_files(self, parent_fid: str, query: str, max_depth: int = 1) -> list[dict]:
        """Search files by name recursively up to max_depth levels.
        Returns list of {name, fid, size, path} dicts."""
        results: list[dict] = []
        self._search_recursive(parent_fid, query.lower(), "", max_depth, results)
        return results

    def _search_recursive(self, fid: str, query: str, path_prefix: str,
                          depth: int, results: list[dict]):
        page = 1
        while True:
            resp = self.list_folder(fid, page=page, size=200)
            entries = resp.get("data", {}).get("list", [])
            if not entries:
                break
            for e in entries:
                name = e.get("file_name", "")
                if query in name.lower():
                    size = e.get("size", 0)
                    results.append({
                        "name": name,
                        "fid": e.get("fid", ""),
                        "size": f"{size / 1024 / 1024:.1f}MB" if size > 1024 * 1024
                        else f"{size / 1024:.1f}KB",
                        "path": f"{path_prefix}/{name}",
                        "is_dir": bool(e.get("dir")),
                    })
                if e.get("dir") and depth > 0:
                    sub_path = f"{path_prefix}/{name}"
                    self._search_recursive(e["fid"], query, sub_path, depth - 1, results)
            total = resp.get("data", {}).get("total", 0)
            if total == 0 or page * 200 >= total:
                break
            page += 1

    def close(self):
        self.client.close()
