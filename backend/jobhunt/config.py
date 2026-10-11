"""Configuration: env vars + YAML source registry."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class SourceConfig:
    name: str
    type: str
    label: str = ""
    coverage: str = ""
    docs_url: str = ""
    params: dict = field(default_factory=dict)


@dataclass
class Settings:
    db_path: Path = PROJECT_ROOT / "data" / "jobhunt.db"
    timezone: str = "Asia/Karachi"
    digest_dir: Path = PROJECT_ROOT / "data" / "digests"
    per_source_timeout: int = 25
    max_jobs_per_source: int = 150
    min_seconds_between_requests: float = 1.0
    verify_new_listings: bool = True
    verify_max_per_run: int = 60
    sources: list = field(default_factory=list)

    def ensure_dirs(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.digest_dir.mkdir(parents=True, exist_ok=True)


def load_settings(config_path: str | None = None, env: dict | None = None) -> Settings:
    env = env or os.environ
    s = Settings()
    if env.get("JOBHUNT_DB_PATH"):
        s.db_path = Path(env["JOBHUNT_DB_PATH"])
    if env.get("JOBHUNT_TIMEZONE"):
        s.timezone = env["JOBHUNT_TIMEZONE"]
    if env.get("JOBHUNT_DIGEST_DIR"):
        s.digest_dir = Path(env["JOBHUNT_DIGEST_DIR"])

    cfg_file = Path(config_path) if config_path else PROJECT_ROOT / "config.yaml"
    if not cfg_file.exists():
        cfg_file = PROJECT_ROOT / "config.yaml.example"
    with open(cfg_file) as f:
        raw = yaml.safe_load(f) or {}

    disc = raw.get("discovery", {})
    s.per_source_timeout = int(disc.get("per_source_timeout_seconds", 25))
    s.max_jobs_per_source = int(disc.get("max_jobs_per_source", 150))
    s.min_seconds_between_requests = float(disc.get("min_seconds_between_requests", 1.0))
    s.verify_new_listings = bool(disc.get("verify_new_listings", True))
    s.verify_max_per_run = int(disc.get("verify_max_per_run", 60))

    for entry in raw.get("sources", []):
        params = {k: v for k, v in entry.items()
                  if k not in {"name", "type", "label", "coverage", "docs_url"}}
        s.sources.append(SourceConfig(
            name=entry["name"], type=entry["type"],
            label=entry.get("label", entry["name"]),
            coverage=entry.get("coverage", ""),
            docs_url=entry.get("docs_url", ""),
            params=params,
        ))
    s.ensure_dirs()
    return s
