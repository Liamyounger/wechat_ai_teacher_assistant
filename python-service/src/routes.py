import logging
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .quark.cookie import CookieManager
from .quark.api import QuarkClient
from .download.queue import task_queue
from .articles.searcher import ArticleSearcher
from .articles.extractor import ArticleExtractor
from .links.quark_share import QuarkShareClient, extract_share_id
from config.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")

# Lazy-init globals
_cookie_mgr: CookieManager | None = None
_quark_client: QuarkClient | None = None
_article_searcher: ArticleSearcher | None = None
_article_extractor: ArticleExtractor | None = None
_share_client: QuarkShareClient | None = None

def get_quark() -> QuarkClient:
    global _cookie_mgr, _quark_client
    if _quark_client is None:
        _cookie_mgr = CookieManager(settings.cookies_path)
        _quark_client = QuarkClient(_cookie_mgr)
    return _quark_client

def get_article_searcher() -> ArticleSearcher:
    global _article_searcher
    if _article_searcher is None:
        _article_searcher = ArticleSearcher()
    return _article_searcher

def get_article_extractor() -> ArticleExtractor:
    global _article_extractor
    if _article_extractor is None:
        _article_extractor = ArticleExtractor()
    return _article_extractor

def get_share_client() -> QuarkShareClient:
    global _cookie_mgr, _share_client
    if _share_client is None:
        _cookie_mgr = CookieManager(settings.cookies_path)
        _share_client = QuarkShareClient(_cookie_mgr)
    return _share_client

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
        results = api.search_files(folder_id, q.strip(), max_depth=1)
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

class ShareRequest(BaseModel):
    file_id: str
    filename: str

@router.post("/share")
async def create_share(req: ShareRequest):
    """Create a public share link for a file (for files > 25MB that can't be sent via WeChat)."""
    try:
        api = get_quark()
        url = api.create_share_url(req.file_id, req.filename)
        return {"share_url": url, "filename": req.filename}
    except PermissionError as e:
        raise HTTPException(status_code=401, detail={"error": "cookie_expired", "message": str(e)})
    except Exception as e:
        logger.exception("Share creation failed")
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


# ── Article search routes ──────────────────────────────────────────

@router.get("/articles/search")
async def search_articles(q: str = "", page: int = 1):
    """Search WeChat official account articles via Sogou."""
    if not q.strip():
        return {"query": q, "articles": [], "page": page, "has_more": False}
    try:
        searcher = get_article_searcher()
        result = searcher.search(q.strip(), max(page, 1))
        return result
    except Exception as e:
        logger.exception("Article search failed")
        raise HTTPException(status_code=500, detail=str(e))


class ExtractRequest(BaseModel):
    sogou_url: str = ""


@router.post("/articles/extract")
async def extract_article_links(req: ExtractRequest):
    """Resolve a Sogou URL and extract sharing links from the article."""
    if not req.sogou_url:
        raise HTTPException(status_code=400, detail="sogou_url is required")
    try:
        searcher = get_article_searcher()
        extractor = get_article_extractor()

        # Step 1: resolve Sogou redirect → real mp.weixin.qq.com URL
        article_url = searcher.resolve_article_url(req.sogou_url)
        if not article_url:
            raise HTTPException(status_code=502, detail="Failed to resolve article URL")

        # Step 2: extract sharing links
        result = extractor.extract_links(article_url)
        return result
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"Upstream error: {e.response.status_code}")
    except Exception as e:
        logger.exception("Article extraction failed")
        raise HTTPException(status_code=500, detail=str(e))


# ── Share link routes ───────────────────────────────────────────────

@router.get("/share/browse")
async def browse_share(url: str = "", path: str = ""):
    """Browse a Quark share link. path is fid of the folder to browse."""
    if not url:
        raise HTTPException(status_code=400, detail="url is required")
    share_id = extract_share_id(url)
    if not share_id:
        raise HTTPException(status_code=400, detail="Could not extract share_id from URL")
    try:
        sc = get_share_client()
        pdir_fid = path if path else "0"
        result = sc.get_share_files(share_id, pdir_fid)
        return {"share_id": share_id, "pdir_fid": pdir_fid, **result}
    except PermissionError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        logger.exception("Share browse failed")
        raise HTTPException(status_code=500, detail=str(e))


class ShareDownloadRequest(BaseModel):
    share_url: str
    fid: str
    filename: str = ""


@router.post("/share/download")
async def submit_share_download(req: ShareDownloadRequest):
    """Submit a download task from a shared file. Supports PDF splitting."""
    share_id = extract_share_id(req.share_url)
    if not share_id:
        raise HTTPException(status_code=400, detail="Could not extract share_id from URL")
    task = task_queue.submit_share(share_id, req.fid, req.filename)
    return task.to_dict()
