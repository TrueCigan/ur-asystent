"""Admin crawl allowlist. Hosts are not added from application code."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "data" / "allowlist.yaml"


class AllowlistError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def load_allowlist(path: Path | None = None) -> dict:
    raw = yaml.safe_load((path or DEFAULT_PATH).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("crawl"), list):
        raise AllowlistError("invalid_allowlist")
    return raw


def enabled_hosts(path: Path | None = None) -> set[str]:
    data = load_allowlist(path)
    hosts = set()
    for row in data["crawl"]:
        host = str(row.get("host") or "").strip().lower().rstrip(".")
        if not host:
            raise AllowlistError("invalid_allowlist")
        if row.get("enabled") is True:
            hosts.add(host)
    return hosts


def host_of(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise AllowlistError("forbidden_scheme")
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise AllowlistError("forbidden_host")
    return host


def assert_enabled(url: str, path: Path | None = None) -> str:
    host = host_of(url)
    if host not in enabled_hosts(path):
        raise AllowlistError("forbidden_host")
    return host
