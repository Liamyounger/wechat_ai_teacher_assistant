import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .quark.cookie import CookieManager
from .quark.api import QuarkClient
from .download.queue import task_queue
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

@router.get("/search")
async def search_files(q: str = "", path: str = "/"):
    """Search files/folders by name recursively from a starting path."""
    if not q.strip():
        return {"query": q, "results": []}
    try:
        api = get_quark()
        folder_id = api.resolve_path(path)
        results = api.search_files(folder_id, q.strip(), max_depth=0)
        # Limit results to avoid huge responses
        return {"query": q, "results": results[:30]}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=401, detail={"error": "cookie_expired", "message": str(e)})
    except Exception as e:
        logger.exception("Search failed")
        raise HTTPException(status_code=500, detail=str(e))


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
