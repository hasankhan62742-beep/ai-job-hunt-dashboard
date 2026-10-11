"""Security utilities: SSRF protection, URL validation, prompt-injection guards.

All retrieved content (job descriptions, CVs, web pages) is UNTRUSTED data.
It is never treated as instructions.
"""
from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse

ALLOWED_SCHEMES = {"http", "https"}

# Cloud metadata + link-local + loopback ranges are never fetched.
_BLOCKED_HOSTNAMES = {
    "localhost",
    "metadata.google.internal",
}
_METADATA_IPS = ("169.254.169.254", "fd00:ec2::254")

_INSTRUCTION_PATTERNS = [
    r"ignore (all |any )?previous instructions",
    r"disregard (all |any )?(prior|previous) instructions",
    r"system prompt",
    r"you are now ",
    r"new instructions?:",
    r"override (the |your )?(system|previous)",
    r"jailbreak",
    r"do not (tell|mention|reveal)",
]


# Strictly internal ranges for SSRF purposes. (We deliberately do NOT use
# ip.is_private/is_reserved: those include benchmark/test ranges such as
# 198.18.0.0/15 that sandboxed egress proxies legitimately resolve to.)
_SSRF_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local: cloud metadata
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("::/128"),
]


def _ip_is_internal(ip: "ipaddress._BaseAddress") -> bool:
    return any(ip in net for net in _SSRF_NETWORKS)


def is_private_host(host: str) -> bool:
    """True if the host is internal-only infrastructure (SSRF guard)."""
    host = host.strip().lower().rstrip(".")
    if host in _BLOCKED_HOSTNAMES or host in _METADATA_IPS:
        return True
    try:
        return _ip_is_internal(ipaddress.ip_address(host))
    except ValueError:
        pass  # hostname, resolve it
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, ValueError):
        return True  # unresolvable -> do not fetch
    return any(_ip_is_internal(ipaddress.ip_address(sa[0])) for _, _, _, _, sa in infos)


def safe_url(url: str) -> bool:
    """True only if the URL is http(s) and does not point at internal infra."""
    if not url or len(url) > 2048:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ALLOWED_SCHEMES or not parsed.hostname:
        return False
    if "@" in parsed.netloc:  # userinfo smuggling
        return False
    return not is_private_host(parsed.hostname)


def sanitize_untrusted_text(text: str, max_len: int = 20000) -> str:
    """Strip control chars, cap length, neutralize instruction-like content.

    We do NOT execute or obey anything inside retrieved text; this function
    additionally flags it so downstream LLM calls can wrap it as data.
    """
    if not text:
        return ""
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)
    text = text[:max_len]
    return text.strip()


def looks_like_instruction(text: str) -> bool:
    lowered = text.lower()
    return any(re.search(p, lowered) for p in _INSTRUCTION_PATTERNS)


def redact_pii_for_logs(text: str) -> str:
    text = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[email]", text)
    text = re.sub(r"\+?\d[\d\s\-()]{7,}\d", "[phone]", text)
    return text
