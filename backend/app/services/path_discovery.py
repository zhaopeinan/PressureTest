from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

from app.config import settings

_STATIC_EXT = {
    ".css",
    ".js",
    ".mjs",
    ".map",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".mp4",
    ".mp3",
    ".pdf",
    ".zip",
}

_DYNAMIC_MARKERS = (":", "${", "{", "}", "*", "?")

_HREF_ATTR_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_SCRIPT_SRC_RE = re.compile(r"""<script[^>]+src=["']([^"']+)["']""", re.IGNORECASE)
_BACKTICK_PATH_RE = re.compile(r"`(/[A-Za-z0-9_\-./]{1,120})`")
_QUOTE_PATH_RE = re.compile(
    r"""["'](/(?:api|portal|auth|celebration|system|admin|captcha|init)[^"']{0,120})["']"""
)
_HASH_ROUTE_RE = re.compile(r"""#(/[A-Za-z0-9_\-./]{1,80})""")
_NAV_PATH_RE = re.compile(r"""path:\s*`(/[^`$:{*]{1,80})`""")
_BASE_URL_RE = re.compile(
    r"""baseURL\s*:\s*(?:`([^`]+)`|["']([^"']+)["'])""",
    re.IGNORECASE,
)
_PATH_VAR_RE = re.compile(
    r"""(?:var|let|const)\s+([$\w]+)\s*=\s*(?:`(/[^`$]{1,100})`|["'](/[^"']{1,100})["'])"""
)
_URL_BACKTICK_RE = re.compile(r"""url\s*:\s*`(/[^`$]{1,120})`""")
_URL_TMPL_RE = re.compile(r"""url\s*:\s*`\$\{([$\w]+)\}([^`]*)`""")
_LAZY_CHUNK_RE = re.compile(r"""["']\./([A-Za-z0-9_\-]+\.[A-Za-z0-9]+\.js)["']""")
_API_PREFIXES = (
    "/api",
    "/portal",
    "/auth",
    "/celebration",
    "/system",
    "/admin",
    "/captcha",
    "/init",
    "/japi",
    "/v1",
    "/pois",
)


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.hrefs.append(value)


def _host_allowed(host: str) -> str:
    parsed = urlparse(host if "://" in host else f"https://{host}")
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValueError("host must include a valid hostname")
    allowed = settings.allowed_host_set()
    if hostname not in allowed and not any(hostname.endswith(f".{h}") for h in allowed):
        raise ValueError(
            f"host '{hostname}' is not in allowlist: {', '.join(sorted(allowed))}"
        )
    scheme = parsed.scheme or "https"
    return f"{scheme}://{hostname}" + (f":{parsed.port}" if parsed.port else "")


def _is_static(path: str) -> bool:
    lower = path.lower().split("?", 1)[0]
    return any(lower.endswith(ext) for ext in _STATIC_EXT)


def _is_stable_path(path: str) -> bool:
    if not path.startswith("/"):
        return False
    if any(marker in path for marker in _DYNAMIC_MARKERS):
        return False
    if path in {"//", "/?", "/"}:
        return path == "/"
    return True


def _normalize_path(base: str, href: str) -> str | None:
    href = (href or "").strip()
    if not href or href.startswith(("mailto:", "tel:", "javascript:", "data:")):
        return None
    # Hash-only routes still hit "/"
    if href.startswith("#"):
        return "/"

    absolute = urljoin(base if base.endswith("/") else base + "/", href)
    parsed = urlparse(absolute)
    base_parsed = urlparse(base)
    if parsed.scheme not in {"http", "https"}:
        return None
    if (parsed.hostname or "").lower() != (base_parsed.hostname or "").lower():
        return None

    path = parsed.path or "/"
    if not path.startswith("/"):
        path = f"/{path}"
    return path


def _extract_html_links(html: str, base: str) -> list[str]:
    parser = _LinkParser()
    try:
        parser.feed(html)
        hrefs = parser.hrefs
    except Exception:
        hrefs = _HREF_ATTR_RE.findall(html)

    found: list[str] = []
    seen: set[str] = set()
    for href in hrefs:
        path = _normalize_path(base, href)
        if not path or path in seen or _is_static(path):
            continue
        seen.add(path)
        found.append(path)
    return found


def _extract_script_srcs(html: str, base: str) -> list[str]:
    urls: list[str] = []
    for src in _SCRIPT_SRC_RE.findall(html):
        absolute = urljoin(base if base.endswith("/") else base + "/", src)
        parsed = urlparse(absolute)
        base_parsed = urlparse(base)
        if (parsed.hostname or "").lower() != (base_parsed.hostname or "").lower():
            continue
        urls.append(absolute)
    return urls


def _api_mount_from_base_url(base_url: str, page_origin: str) -> str | None:
    """Return path mount like '/api' from an axios baseURL."""
    raw = (base_url or "").strip()
    if not raw:
        return None
    if raw.startswith("/"):
        return raw.rstrip("/") or None
    absolute = urljoin(page_origin.rstrip("/") + "/", raw)
    parsed = urlparse(absolute)
    origin = urlparse(page_origin)
    if (parsed.hostname or "").lower() != (origin.hostname or "").lower():
        return None
    path = (parsed.path or "").rstrip("/")
    return path or None


def _with_api_mount(path: str, api_mount: str | None) -> set[str]:
    out = {path}
    if not api_mount:
        return out
    if path.startswith(api_mount + "/") or path == api_mount:
        return out
    if path.startswith("/api/"):
        return out
    # Relative SPA paths are usually under axios baseURL (/api + /portal/...).
    if any(path.startswith(p) for p in _API_PREFIXES if p != "/api"):
        joined = f"{api_mount}{path}" if path.startswith("/") else f"{api_mount}/{path}"
        out.add(joined)
    return out


def _extract_candidates_from_js(
    js_text: str,
    *,
    api_mount: str | None = None,
) -> tuple[list[str], list[str], list[str], str | None]:
    """Return (page_like_paths, api_like_paths, lazy_chunk_names, detected_api_mount)."""
    pages: set[str] = set()
    apis: set[str] = set()
    detected_mount = api_mount

    for match in _BASE_URL_RE.finditer(js_text):
        candidate = match.group(1) or match.group(2)
        # Keep first absolute/relative mount that looks like an API root.
        if candidate and ("api" in candidate.lower() or candidate.startswith("/")):
            # Stash raw; caller resolves against page origin when needed.
            if candidate.startswith("http") or candidate.startswith("/"):
                detected_mount = detected_mount or candidate

    path_vars: dict[str, str] = {}
    for match in _PATH_VAR_RE.finditer(js_text):
        name = match.group(1)
        value = match.group(2) or match.group(3)
        if value:
            path_vars[name] = value

    def _keep(path: str, *, as_api: bool) -> None:
        if not _is_stable_path(path) or _is_static(path):
            return
        bucket = apis if as_api else pages
        for item in _with_api_mount(path, api_mount if api_mount and api_mount.startswith("/") else None):
            if _is_stable_path(item):
                bucket.add(item)

    for path in _NAV_PATH_RE.findall(js_text):
        _keep(path, as_api=False)

    for path in _URL_BACKTICK_RE.findall(js_text):
        _keep(path, as_api=True)

    for match in _URL_TMPL_RE.finditer(js_text):
        var_name, suffix = match.group(1), match.group(2) or ""
        prefix = path_vars.get(var_name)
        if not prefix:
            continue
        # Drop dynamic segments like ${e}
        if "${" in suffix or "{" in suffix:
            # Keep the static prefix directory itself.
            _keep(prefix if prefix.endswith("/") else f"{prefix}/", as_api=True)
            continue
        _keep(f"{prefix}{suffix}", as_api=True)

    for path in _BACKTICK_PATH_RE.findall(js_text):
        as_api = any(path.startswith(prefix) for prefix in _API_PREFIXES)
        _keep(path, as_api=as_api)

    for path in _QUOTE_PATH_RE.findall(js_text):
        _keep(path, as_api=True)

    for _ in _HASH_ROUTE_RE.findall(js_text):
        pages.add("/")

    for value in path_vars.values():
        as_api = any(value.startswith(prefix) for prefix in _API_PREFIXES)
        _keep(value, as_api=as_api)

    lazy_chunks = sorted(set(_LAZY_CHUNK_RE.findall(js_text)))
    return sorted(pages), sorted(apis), lazy_chunks, detected_mount


async def _probe_paths(
    client: httpx.AsyncClient,
    base: str,
    candidates: list[str],
    *,
    limit: int = 120,
    concurrency: int = 12,
) -> list[dict]:
    import asyncio

    unique: list[str] = []
    seen: set[str] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
        if len(unique) >= limit:
            break

    sem = asyncio.Semaphore(concurrency)
    results: list[dict] = []

    async def _one(path: str) -> dict | None:
        async with sem:
            try:
                resp = await client.get(f"{base}{path}")
            except Exception:
                return None
        if resp.status_code >= 400:
            return None
        content_type = (resp.headers.get("content-type") or "").lower()
        if "json" in content_type or path.startswith(("/api", "/v1", "/japi")):
            kind = "api"
        elif _is_static(path):
            kind = "asset"
        else:
            kind = "page"
        return {
            "path": path,
            "kind": kind,
            "status_code": resp.status_code,
            "content_type": content_type.split(";")[0],
        }

    probed = await asyncio.gather(*[_one(path) for path in unique])
    for item in probed:
        if item:
            results.append(item)
    return results


def _chunk_priority(name: str) -> int:
    lower = name.lower()
    score = 0
    for key in (
        "guest",
        "login",
        "auth",
        "content",
        "portal",
        "api",
        "home",
        "schedule",
        "meal",
        "car",
        "seat",
        "contact",
        "feedback",
        "dict",
    ):
        if key in lower:
            score += 1
    # Deprioritize pure UI/vendor-ish chunks.
    for key in ("style", "checkbox", "footer", "hero", "sanitize", "crypto", "mock"):
        if key in lower:
            score -= 2
    return score


async def discover_paths(
    host: str,
    *,
    start_path: str = "/",
    max_pages: int = 1,
    timeout: float = 8.0,
) -> dict:
    """
    Discover pressurable paths:
    1) HTML <a href> on start page
    2) SPA routes / API hints from entry + lazy JS chunks
    3) Probe candidates and keep only reachable (HTTP < 400) paths
    """
    import asyncio

    base = _host_allowed(host.rstrip("/"))
    start = start_path if start_path.startswith("/") else f"/{start_path}"
    max_pages = max(1, min(int(max_pages), 5))

    headers = {
        "User-Agent": "PressureTest-PathDiscovery/0.1",
        "Accept": "*/*",
    }

    warnings: list[str] = []
    page_candidates: list[str] = [start]
    api_candidates: list[str] = []
    asset_candidates: list[str] = []
    fetched = 0
    api_mount: str | None = None

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(timeout, connect=5.0),
        headers=headers,
        verify=True,
    ) as client:
        start_url = f"{base}{start}"
        try:
            home = await client.get(start_url)
            fetched += 1
        except Exception as exc:
            raise ValueError(f"failed to fetch {start_url}: {exc}") from exc

        if home.status_code >= 400:
            warnings.append(f"{start} returned HTTP {home.status_code}")

        html = home.text or ""
        content_type = (home.headers.get("content-type") or "").lower()

        for link in _extract_html_links(html, str(home.url)):
            if link not in page_candidates:
                page_candidates.append(link)

        for href in _HREF_ATTR_RE.findall(html):
            path = _normalize_path(str(home.url), href)
            if path and _is_static(path) and path not in asset_candidates:
                asset_candidates.append(path)

        if "html" in content_type or html.lstrip().startswith("<"):
            script_urls = _extract_script_srcs(html, str(home.url))
            if script_urls:
                warnings.append(
                    "检测到前端 SPA：将解析入口 JS 与懒加载分包中的接口路径。"
                )

            # Entry scripts first, then prioritized lazy chunks (capped + parallel).
            max_js = 16
            pending: list[str] = list(script_urls)
            seen_js: set[str] = set()
            js_sem = asyncio.Semaphore(6)

            async def _fetch_js(url: str) -> tuple[str, str] | None:
                nonlocal fetched
                async with js_sem:
                    try:
                        js_resp = await client.get(url)
                        fetched += 1
                    except Exception as exc:
                        warnings.append(f"js fetch failed: {exc}")
                        return None
                if js_resp.status_code >= 400:
                    return None
                return url, js_resp.text or ""

            while pending and len(seen_js) < max_js:
                batch: list[str] = []
                while pending and len(seen_js) + len(batch) < max_js and len(batch) < 6:
                    url = pending.pop(0)
                    if url in seen_js:
                        continue
                    seen_js.add(url)
                    batch.append(url)
                if not batch:
                    break

                fetched_js = await asyncio.gather(*[_fetch_js(url) for url in batch])
                for item in fetched_js:
                    if not item:
                        continue
                    script_url, js_text = item
                    pages, apis, lazy_chunks, detected = _extract_candidates_from_js(
                        js_text,
                        api_mount=api_mount
                        if (api_mount and api_mount.startswith("/"))
                        else None,
                    )
                    if detected and not (api_mount and api_mount.startswith("/")):
                        mount = _api_mount_from_base_url(detected, base)
                        if mount:
                            api_mount = mount
                            expanded: list[str] = []
                            for path in api_candidates:
                                expanded.extend(_with_api_mount(path, api_mount))
                            for path in expanded:
                                if path not in api_candidates:
                                    api_candidates.append(path)

                    for path in pages:
                        if path not in page_candidates:
                            page_candidates.append(path)
                    for path in apis:
                        for mounted in _with_api_mount(path, api_mount):
                            if mounted not in api_candidates:
                                api_candidates.append(mounted)

                    script_dir = script_url.rsplit("/", 1)[0] + "/"
                    ranked = sorted(lazy_chunks, key=_chunk_priority, reverse=True)
                    for chunk in ranked:
                        chunk_url = urljoin(script_dir, chunk)
                        if chunk_url not in seen_js and chunk_url not in pending:
                            pending.append(chunk_url)

            if api_mount:
                warnings.append(f"检测到 API 前缀：{api_mount}")

        queue = [p for p in page_candidates if p != start][: max_pages - 1]
        while queue and fetched < max_pages + 2:
            path = queue.pop(0)
            try:
                resp = await client.get(f"{base}{path}")
                fetched += 1
            except Exception:
                continue
            ctype = (resp.headers.get("content-type") or "").lower()
            if resp.status_code >= 400 or "html" not in ctype:
                continue
            for link in _extract_html_links(resp.text, str(resp.url)):
                if link not in page_candidates:
                    page_candidates.append(link)

        probe_list: list[str] = []
        for group in ([start], api_candidates, asset_candidates, page_candidates):
            for path in group:
                if path not in probe_list:
                    probe_list.append(path)

        discovered_items = await _probe_paths(client, base, probe_list, limit=120)

    paths = [item["path"] for item in discovered_items]
    if start not in paths and home.status_code < 400:
        paths.insert(0, start)
        discovered_items.insert(
            0,
            {
                "path": start,
                "kind": "page",
                "status_code": home.status_code,
                "content_type": (home.headers.get("content-type") or "").split(";")[0],
            },
        )

    return {
        "host": base,
        "start_path": start,
        "paths": paths,
        "items": discovered_items,
        "fetched_pages": fetched,
        "warnings": warnings,
    }
