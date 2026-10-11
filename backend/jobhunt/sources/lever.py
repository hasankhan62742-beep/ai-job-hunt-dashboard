"""Lever public Postings API (no auth for reads).

Docs: https://github.com/lever/postings-api
Endpoint: https://api.lever.co/v0/postings/{company}?mode=json
EU-hosted boards use https://api.eu.lever.co/...
Company slug = the slug in https://jobs.lever.co/{slug} (case matters).
"""
from __future__ import annotations

from ..models import RawJob
from .base import SourceAdapter

HOSTS = {"us": "https://api.lever.co", "eu": "https://api.eu.lever.co"}


class LeverAdapter(SourceAdapter):
    def __init__(self, slug: str, region: str = "us", **kwargs):
        super().__init__(timeout=kwargs.pop("timeout", 25),
                         min_interval=kwargs.pop("min_interval", 1.0))
        self.slug = slug
        self.region = region if region in HOSTS else "us"
        self.name = f"lever-{slug.lower()}"
        self.label = kwargs.pop("label", f"Lever board: {slug}")

    def fetch(self) -> list[RawJob]:
        url = f"{HOSTS[self.region]}/v0/postings/{self.slug}"
        data = self._get_json(url, params={"mode": "json"})
        if isinstance(data, dict) and data.get("ok") is False:
            from .base import SourceError
            raise SourceError(f"{self.name}: API error: {data.get('error')}")
        jobs = []
        for j in data if isinstance(data, list) else []:
            cats = j.get("categories") or {}
            loc = cats.get("location", "") or j.get("workplaceType", "")
            jobs.append(RawJob(
                source_name=self.name,
                title=j.get("text", "").strip(),
                employer=self.slug,
                source_url=j.get("hostedUrl", ""),
                original_posting_url=j.get("hostedUrl", ""),
                apply_url=j.get("applyUrl", "") or j.get("hostedUrl", ""),
                location=loc,
                employment_type=cats.get("commitment", ""),
                description_html=j.get("description", "") or "",
                extra={"lever_id": j.get("id"),
                       "created_at": j.get("createdAt"),
                       "team": cats.get("team")},
            ))
        return jobs
