"""RemoteOK public API (no auth for reads).

Terms (https://remoteok.com/api): link back to Remote OK and mention it as
the source; do not use its logo without written permission.
Optional tag filter narrows results server-side-ish (client-side here).
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..models import RawJob
from .base import SourceAdapter

API = "https://remoteok.com/api"


class RemoteOKAdapter(SourceAdapter):
    def __init__(self, tags: list | None = None, **kwargs):
        super().__init__(timeout=kwargs.pop("timeout", 25),
                         min_interval=kwargs.pop("min_interval", 1.0))
        self.name = "remoteok"
        self.label = kwargs.pop("label", "RemoteOK (remote-only)")
        self.tags = [t.lower() for t in (tags or [])]

    def fetch(self) -> list[RawJob]:
        data = self._get_json(API)
        jobs = []
        for j in data:
            if not isinstance(j, dict) or "position" not in j:
                continue  # first element is the legal notice
            job_tags = [t.lower() for t in (j.get("tags") or [])]
            if self.tags and not any(t in job_tags for t in self.tags):
                continue
            epoch = j.get("epoch")
            posted = ""
            if epoch:
                posted = datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()
            jobs.append(RawJob(
                source_name=self.name,
                title=(j.get("position") or "").strip(),
                employer=(j.get("company") or "").strip(),
                source_url=j.get("url", ""),
                original_posting_url=j.get("url", ""),
                apply_url=j.get("apply_url", "") or j.get("url", ""),
                location="Remote",
                description_html=j.get("description", "") or "",
                salary_text=j.get("salary", "") or "",
                posted_at=posted,
                extra={"remoteok_id": j.get("id"), "tags": job_tags,
                       "logo": j.get("company_logo", "")},
            ))
        return jobs
