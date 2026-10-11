"""Greenhouse public Job Board API (no auth for reads).

Docs: https://developers.greenhouse.io/job-board.html
Board token = slug in https://boards.greenhouse.io/{token}
"""
from __future__ import annotations

from ..models import RawJob
from .base import SourceAdapter

API = "https://boards-api.greenhouse.io/v1/boards"


class GreenhouseAdapter(SourceAdapter):
    def __init__(self, token: str, **kwargs):
        super().__init__(timeout=kwargs.pop("timeout", 25),
                         min_interval=kwargs.pop("min_interval", 1.0))
        self.token = token
        self.name = f"greenhouse-{token}"
        self.label = kwargs.pop("label", f"Greenhouse board: {token}")

    def fetch(self) -> list[RawJob]:
        data = self._get_json(f"{API}/{self.token}/jobs", params={"content": "false"})
        jobs = []
        for j in data.get("jobs", []):
            loc = (j.get("location") or {}).get("name", "")
            jobs.append(RawJob(
                source_name=self.name,
                title=j.get("title", "").strip(),
                employer=self.token,
                source_url=j.get("absolute_url", ""),
                original_posting_url=j.get("absolute_url", ""),
                apply_url=j.get("absolute_url", ""),
                location=loc,
                employment_type="",
                extra={"greenhouse_id": j.get("id"),
                       "updated_at": j.get("updated_at"),
                       "departments": [d.get("name") for d in j.get("departments", [])]},
            ))
        return jobs
