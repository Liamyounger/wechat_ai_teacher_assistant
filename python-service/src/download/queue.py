import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from config.settings import settings

logger = logging.getLogger(__name__)

class DownloadTask:
    def __init__(self, file_id: str, filename: str, share_id: str = ""):
        self.task_id = uuid.uuid4().hex[:12]
        self.file_id = file_id
        self.share_id = share_id   # non-empty if this is a share download
        self.filename = filename
        self.status = "queued"       # queued | downloading | done | failed
        self.progress = 0
        self.local_path = ""
        self.parts: list[str] = []   # multiple paths if PDF was split
        self.error = ""
        self.created_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "progress": self.progress,
            "local_path": self.local_path,
            "parts": self.parts,
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

    def submit_share(self, share_id: str, fid: str, filename: str = "") -> DownloadTask:
        task = DownloadTask(fid, filename or fid, share_id=share_id)
        with self._lock:
            self._tasks[task.task_id] = task
            self._cv.notify()
        logger.info(f"Share download task queued: {task.task_id} ({filename})")
        return task

    def get(self, task_id: str) -> DownloadTask | None:
        with self._lock:
            return self._tasks.get(task_id)

    def _worker(self):
        """Serial download worker — one file at a time. Handles share downloads
        and auto-splits PDFs that exceed the 20MB iLink limit."""
        from ..quark.api import QuarkClient
        from ..quark.cookie import CookieManager
        from ..links.quark_share import QuarkShareClient
        from .fetcher import download_file

        cm = CookieManager(settings.cookies_path)
        api = QuarkClient(cm)
        share_client = QuarkShareClient(cm)

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

                # Get download URL — from share or from user's drive
                if task.share_id:
                    download_url, filename = share_client.get_download_url(
                        task.share_id, task.file_id
                    )
                else:
                    download_url, filename = api.get_download_url(task.file_id)

                if not task.filename or task.filename == task.file_id:
                    task.filename = filename

                dest_dir = Path(settings.download_dir) / task.task_id
                dest_dir.mkdir(parents=True, exist_ok=True)

                def progress_cb(pct: int):
                    task.progress = pct

                local = download_file(download_url, str(dest_dir / filename),
                                      progress_cb=progress_cb,
                                      cookie_dict=cm.to_dict())
                task.local_path = local
                task.progress = 100

                # Check if PDF needs splitting
                from ..split.pdf_splitter import split_pdf_if_needed
                chunk_paths = split_pdf_if_needed(local)
                if len(chunk_paths) > 1:
                    task.parts = chunk_paths
                    logger.info(f"PDF split into {len(chunk_paths)} parts: {task.filename}")

                task.status = "done"
                logger.info(f"Download complete: {task.filename}")
            except Exception as e:
                task.status = "failed"
                task.error = str(e)
                logger.error(f"Download failed: {task.filename} — {e}")

        api.close()
        share_client.close()

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
                if task.local_path:
                    try:
                        Path(task.local_path).unlink(missing_ok=True)
                        Path(task.local_path).parent.rmdir()
                    except OSError:
                        pass

task_queue = DownloadQueue()
