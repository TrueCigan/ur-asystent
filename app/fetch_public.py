"""Public fetch with allowlist, SSRF checks, robots, size caps, and two retries.

Redirects are followed manually. Each hop is resolved and checked again.
Tests pass resolve/request/robots callables and never open a socket.
"""
from __future__ import annotations

import ipaddress
import random
import re
import time
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from allowlist import assert_enabled, host_of

HTML_MAX_BYTES = 5 * 1024 * 1024
PDF_MAX_BYTES = 20 * 1024 * 1024
PDF_MAX_PAGES = 200
TIMEOUT_SEC = 15
RETRIES = 2
MAX_HOPS = 5
UA = "UR-Assistant-Prototype/0.1 (student project; polite crawler)"

METADATA_NAMES = {
    "metadata.google.internal",
    "metadata.google.com",
}


class FetchError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class PublicResponse:
    def __init__(self, status: int, headers: dict, content: bytes, url: str):
        self.status_code = status
        self.headers = {str(k).lower(): v for k, v in (headers or {}).items()}
        self.content = content or b""
        self.url = url

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", "replace")

    def json(self):
        import json
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise FetchError(f"http_{self.status_code}")


def ip_denied(value: str) -> bool:
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return True
    if (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    ):
        return True
    return False


def name_denied(host: str) -> bool:
    host = (host or "").strip().lower().rstrip(".")
    if host in METADATA_NAMES:
        return True
    if host.endswith(".metadata.google.internal"):
        return True
    return False


def check_resolution(host: str, addresses: list[str]) -> None:
    if name_denied(host):
        raise FetchError("ssrf")
    literal = _literal_ip(host)
    if literal is not None:
        if ip_denied(literal):
            raise FetchError("ssrf")
        return
    if not addresses:
        raise FetchError("ssrf")
    for address in addresses:
        if ip_denied(address):
            raise FetchError("ssrf")


def _literal_ip(host: str) -> str | None:
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return None


def pdf_page_count(data: bytes) -> int:
    """Count page objects. /Pages (the tree) is not a page."""
    return len(re.findall(br"/Type\s*/Page(?!s)\b", data or b""))


def _kind(url: str, content_type: str) -> str:
    ct = (content_type or "").lower()
    path = urlparse(url).path.lower()
    if "pdf" in ct or path.endswith(".pdf"):
        return "pdf"
    return "html"


def _limit(kind: str) -> int:
    return PDF_MAX_BYTES if kind == "pdf" else HTML_MAX_BYTES


def robots_allowed(url: str, robots_body: str | None, status: int) -> bool:
    if status == 404 or robots_body is None:
        return True
    if status >= 400:
        return False
    parser = RobotFileParser()
    parser.parse((robots_body or "").splitlines())
    return parser.can_fetch(UA, url)


def fetch(
    url: str,
    *,
    resolve,
    request,
    robots,
    allow_host=None,
    sleep=time.sleep,
    rand=random.random,
    retries: int = RETRIES,
):
    """GET url. `request` must not follow redirects.

    retries is the number of extra attempts after the first failure (timeout or 5xx).
    """
    allow = allow_host or (lambda candidate: assert_enabled(candidate))
    attempts = 0
    while True:
        try:
            return _once(url, resolve=resolve, request=request, robots=robots, allow_host=allow)
        except FetchError as exc:
            if exc.code not in ("timeout", "unavailable") or attempts >= retries:
                raise
            attempts += 1
            sleep(0.05 + (rand() * 0.2))


def _once(url, *, resolve, request, robots, allow_host):
    current = url
    seen = set()
    for _ in range(MAX_HOPS):
        if current in seen:
            raise FetchError("redirect")
        seen.add(current)
        host = host_of(current)
        addresses = [] if _literal_ip(host) else list(resolve(host) or [])
        check_resolution(host, addresses)
        allow_host(current)
        robots_url = f"{urlparse(current).scheme}://{host}/robots.txt"
        robots_host = host_of(robots_url)
        robots_addresses = [] if _literal_ip(robots_host) else list(resolve(robots_host) or [])
        check_resolution(robots_host, robots_addresses)
        allow_host(robots_url)
        try:
            robots_resp = robots(robots_url, timeout=TIMEOUT_SEC)
        except TimeoutError:
            raise FetchError("timeout") from None
        if not robots_allowed(current, _body_text(robots_resp), _status(robots_resp)):
            raise FetchError("robots")
        try:
            response = request(current, timeout=TIMEOUT_SEC)
        except TimeoutError:
            raise FetchError("timeout") from None
        status = _status(response)
        headers = _headers(response)
        if status in (301, 302, 303, 307, 308):
            location = headers.get("location") or headers.get("Location")
            if not location:
                raise FetchError("redirect")
            current = urljoin(current, location)
            continue
        if status >= 500:
            raise FetchError("unavailable")
        if status >= 400:
            raise FetchError("http")
        content = _content(response)
        kind = _kind(current, headers.get("content-type", ""))
        declared = headers.get("content-length")
        if declared and int(declared) > _limit(kind):
            raise FetchError("too_large")
        if len(content) > _limit(kind):
            raise FetchError("too_large")
        if kind == "pdf" and pdf_page_count(content) > PDF_MAX_PAGES:
            raise FetchError("pdf_pages")
        return PublicResponse(status, headers, content, current)
    raise FetchError("redirect")


def _status(response) -> int:
    if isinstance(response, PublicResponse):
        return response.status_code
    return int(response[0])


def _headers(response) -> dict:
    if isinstance(response, PublicResponse):
        return response.headers
    return {str(k).lower(): v for k, v in (response[1] or {}).items()}


def _content(response) -> bytes:
    if isinstance(response, PublicResponse):
        return response.content
    body = response[2]
    return body if isinstance(body, bytes) else str(body).encode("utf-8")


def _body_text(response) -> str:
    return _content(response).decode("utf-8", "replace")


def public_get(url: str):
    """Live fetch. Not used by offline tests."""
    import httpx

    def resolve(host: str):
        import socket
        infos = socket.getaddrinfo(host, None)
        return [item[4][0] for item in infos]

    def request(target: str, timeout: int):
        try:
            response = httpx.get(
                target,
                timeout=timeout,
                follow_redirects=False,
                headers={"User-Agent": UA},
            )
        except httpx.TimeoutException as exc:
            raise TimeoutError(str(exc)) from None
        return PublicResponse(response.status_code, dict(response.headers), response.content, str(response.url))

    def robots(target: str, timeout: int):
        return request(target, timeout)

    return fetch(url, resolve=resolve, request=request, robots=robots)
