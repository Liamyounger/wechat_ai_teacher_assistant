import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from config.settings import settings
from src.download.queue import task_queue

logging.basicConfig(level=getattr(logging, settings.log_level.upper()))
logger = logging.getLogger("quark-service")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Quark service starting")
    yield
    task_queue.stop()
    logger.info("Quark service stopped")

app = FastAPI(title="Quark Storage Service", version="0.1.0", lifespan=lifespan)

@app.get("/health")
async def health():
    return {"ok": True}
