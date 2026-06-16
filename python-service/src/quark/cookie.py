import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

class CookieManager:
    COOKIE_TTL_SECONDS = 7 * 24 * 3600

    def __init__(self, cookies_path: str):
        self.path = Path(cookies_path)
        self._cookies: list[dict[str, Any]] = []
        self._loaded_at: float = 0

    def _ensure_loaded(self) -> None:
        if not self._cookies:
            self.load()

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            raise FileNotFoundError(f"Cookie file not found: {self.path}")
        raw = json.loads(self.path.read_text())
        self._cookies = raw.get("cookies", raw if isinstance(raw, list) else [])
        if not self._cookies:
            logger.warning("No cookies found; cookie data may be malformed or empty")
        self._loaded_at = time.time()
        logger.info(f"Loaded {len(self._cookies)} cookies from {self.path}")
        return self._cookies

    def to_dict(self) -> dict[str, str]:
        """Return cookies as a {name: value} dict for httpx."""
        self._ensure_loaded()
        return {c["name"]: c["value"] for c in self._cookies if "name" in c and "value" in c}

    def to_header(self) -> str:
        """Return Cookie header string."""
        self._ensure_loaded()
        pairs = [f"{c['name']}={c['value']}" for c in self._cookies if "name" in c and "value" in c]
        return "; ".join(pairs)

    def is_expired(self) -> bool:
        """Heuristic: cookies older than 7 days likely expired."""
        self._ensure_loaded()
        if not self._cookies:
            return True
        elapsed = time.time() - self._loaded_at
        return elapsed > self.COOKIE_TTL_SECONDS

    def save(self, cookies: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"cookies": cookies, "updated_at": time.time()}
        self.path.write_text(json.dumps(data, indent=2))
        self._cookies = cookies
        self._loaded_at = time.time()
        logger.info(f"Saved {len(cookies)} cookies to {self.path}")
