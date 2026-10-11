"""Source registry: builds adapters from config, runs them with isolation.

One source failing never stops the others. Failures are recorded and
reported so coverage limitations are always visible.
"""
from __future__ import annotations

from ..config import Settings
from .base import SourceAdapter, SourceError
from .greenhouse import GreenhouseAdapter
from .lever import LeverAdapter
from .remoteok import RemoteOKAdapter


def build_adapters(settings: Settings) -> list[SourceAdapter]:
    adapters: list[SourceAdapter] = []
    for sc in settings.sources:
        common = dict(timeout=settings.per_source_timeout,
                      min_interval=settings.min_seconds_between_requests,
                      label=sc.label)
        if sc.type == "greenhouse":
            adapters.append(GreenhouseAdapter(token=sc.params["token"], **common))
        elif sc.type == "lever":
            adapters.append(LeverAdapter(slug=sc.params["slug"],
                                         region=sc.params.get("region", "us"), **common))
        elif sc.type == "remoteok":
            adapters.append(RemoteOKAdapter(tags=sc.params.get("tags"), **common))
        else:
            raise ValueError(f"unknown source type: {sc.type} ({sc.name})")
    for adapter, sc in zip(adapters, settings.sources):
        adapter.name = sc.name  # canonical name = registry name, not a guess
    return adapters


def run_all(adapters: list[SourceAdapter], max_per_source: int):
    """Fetch every source; isolate failures. Returns (results, failures)."""
    results: dict[str, list] = {}
    failures: dict[str, str] = {}
    for adapter in adapters:
        try:
            jobs = adapter.fetch()[:max_per_source]
            results[adapter.name] = jobs
        except (SourceError, ValueError) as e:
            failures[adapter.name] = str(e)
        except Exception as e:  # never let one adapter kill the run
            failures[adapter.name] = f"unexpected {type(e).__name__}: {e}"
    return results, failures
