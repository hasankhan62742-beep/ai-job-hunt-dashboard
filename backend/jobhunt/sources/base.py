"""Source adapter interface + shared HTTP behaviour."""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone

import requests

from ..models import RawJob
from ..security import safe_url


class SourceError(Exception):
    pass


class SourceAdapter(ABC):
    """Every source implements fetch() -> list[RawJob]. Failures raise SourceError."""

    name: str = "base"
    label: str = "base"

    def __init__(self, timeout: int = 25, min_interval: float = 1.0):
        self.timeout = timeout
        self.min_interval = min_interval
        self._last_call = 0.0
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "ai-jobhunt-agent/0.1 (+research use)"})

    def _throttle(self):
        wait = self.min_interval - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.time()

    def _get_json(self, url: str, params: dict | None = None):
        if not safe_url(url):
            raise SourceError(f"refusing to fetch unsafe URL: {url}")
        self._throttle()
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            raise SourceError(f"{self.name}: {type(e).__name__}: {e}") from e

    @abstractmethod
    def fetch(self) -> list[RawJob]:
        ...

    def health_dict(self, ok: bool, note: str = "") -> dict:
        return {
            "name": self.name, "label": self.label, "ok": ok, "note": note,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
