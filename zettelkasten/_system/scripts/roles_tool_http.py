#!/usr/bin/env python3
"""HTTP read adapter for the Roles tool seam (CONTRACT §2.2, adapter kind `http`).

A Python-EXECUTABLE adapter (`HARNESS_EXECUTED = False`): the deterministic TOOL
STAGE calls `exec_tool` in-process and gets a `ToolResult` back — the whole seam
(grant → secret-resolve → exec → ephemeral return → audit) runs and is testable
without the Claude Code harness. This is the adapter PLAN 1 proves end-to-end
against a real system.

Interface (CONTRACT §2.2):
  ADAPTER_KIND = "http"
  HARNESS_EXECUTED = False
  exec_tool(spec, request, secret) -> ToolResult

`on_error` is FIXED `declare-unknown` (INV-10): any failure — bad URL, non-http
scheme, timeout, HTTP error, oversized body — returns `ToolResult.unknown`, never
a guessed value. The return is EPHEMERAL (INV-10): the TOOL STAGE feeds it to the
body and never commits the raw body to the repo.

Stdlib-only (`urllib`) — no third-party dependency, cross-platform. Bounded by a
timeout AND a response-size cap so an uncapped read tool cannot hang or bloat the
tick.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from roles_tools import ToolResult, ToolSpec

ADAPTER_KIND = "http"
HARNESS_EXECUTED = False

# Bounds (a read tool must not hang or bloat the tick — INV-28 wall-clock spirit).
DEFAULT_TIMEOUT_SECONDS = 15
MAX_TIMEOUT_SECONDS = 60
MAX_RESPONSE_BYTES = 100_000  # 100 KB — ephemeral reasoning input, not a corpus

# Rate-limit / transient-error backoff. A live API WILL rate-limit a real reconcile — a
# 429 (or a transient 503) is retried with exponential backoff, honouring a `Retry-After`
# header when the server sends one, then HONEST-DEGRADES to `declare-unknown` after
# `MAX_RETRIES` (never a fabricated result). Bounded so the retries can't blow the tick's
# wall-clock budget (INV-28): each sleep is capped and the attempt count is small.
MAX_RETRIES = 3
_RETRYABLE_STATUS: frozenset[int] = frozenset({429, 503})
_BACKOFF_BASE_SECONDS = 1.0
_BACKOFF_CAP_SECONDS = 8.0
_sleep = time.sleep  # module-level so tests can patch it to a no-op (deterministic)


def _retry_after_seconds(exc: urllib.error.HTTPError, attempt: int) -> float:
    """Seconds to wait before the next retry — the server's `Retry-After` (seconds form)
    when present + sane, else capped exponential backoff (base·2^attempt)."""
    hdr = None
    try:
        hdr = exc.headers.get("Retry-After") if exc.headers else None
    except Exception:  # noqa: BLE001 — a malformed header never breaks the retry
        hdr = None
    if hdr is not None:
        try:
            return max(0.0, min(float(str(hdr).strip()), _BACKOFF_CAP_SECONDS))
        except (TypeError, ValueError):
            pass  # HTTP-date form (rare) → fall back to backoff
    return min(_BACKOFF_BASE_SECONDS * (2 ** attempt), _BACKOFF_CAP_SECONDS)
# A read adapter only READS — never a body-triggered write verb (INV-23 direction).
_READ_METHODS: frozenset[str] = frozenset({"GET", "HEAD"})
# An ACT (`direction: act`) tool additionally reaches the write verbs — gated on
# `spec.is_act`, never on the tool id (INV-19). A read tool can never be coerced into a
# write verb (INV-23 — the direction field cannot lie). Acts still run only inside the
# deterministic writer's post-persist step (`roles_act`), under a live mandate + TOCTOU.
_WRITE_METHODS: frozenset[str] = frozenset({"POST", "PATCH", "PUT", "DELETE"})
_ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})


def _host(url: str) -> str:
    try:
        return urllib.parse.urlsplit(url).netloc.lower()
    except (ValueError, AttributeError):
        return ""


def _hostname(url: str) -> str:
    """The bare host of `url` — no port, no `[]` brackets, no userinfo (unlike `_host`)."""
    try:
        return (urllib.parse.urlsplit(url).hostname or "").lower()
    except (ValueError, AttributeError):
        return ""


# SSRF guard (defence-in-depth). A read tool's URL is BODY-supplied, and the body can be
# steered by poisoned tool content it just ingested; a credential-less "public fetch" tool
# has no host pin (the `if secret:` pin below only covers credential-bearing tools). Without
# this a body could point such a tool — or a redirect — at the cloud metadata endpoint and
# read the host's IAM role, or at a link-local service, and the response would land in the
# model's ephemeral context (INV-10). We block **link-local + known cloud-metadata**
# addresses only: loopback / RFC1918 are intentionally NOT blocked (the design lets a
# public-fetch tool roam, and the test fixtures use 127.0.0.1). Literal-IP + one DNS
# resolution catch the direct (`http://169.254.169.254/…`) and hostname
# (`metadata.google.internal`) forms; DNS-rebind (resolve public, connect private) is the
# residual, closed only by a pinned-IP connection in the service-era sandbox.
_METADATA_IPS = frozenset({
    "169.254.169.254",   # AWS / GCP / Azure IMDS
    "fd00:ec2::254",     # AWS IMDSv2 over IPv6
    "100.100.100.200",   # Alibaba Cloud
})


def _ip_is_blocked(ip_text: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return False
    return ip.is_link_local or ip_text in _METADATA_IPS


def _ssrf_blocked_host(hostname: str) -> str:
    """Return the offending address when `hostname` is (or resolves to) a link-local /
    cloud-metadata address, else "". Fail-open on a resolution error (the request then
    fails through the normal declare-unknown path) — never a false block."""
    if not hostname:
        return ""
    try:
        ipaddress.ip_address(hostname)  # a literal IP needs no resolution
        return hostname if _ip_is_blocked(hostname) else ""
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(hostname, None)
    except (OSError, UnicodeError):
        return ""
    for info in infos:
        addr = info[4][0]
        if _ip_is_blocked(addr):
            return addr
    return ""


class _NoAuthLeakRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect handler that STRIPS the `Authorization` header when a redirect
    crosses to a different host (INV-12 — a Bearer token must never reach an
    unintended host). CPython's default handler re-sends every header, including
    Authorization, on a cross-host redirect — a real credential-leak vector for a
    secret-bearing act. This subclass drops Authorization (and Cookie) on a host
    change while leaving same-host redirects untouched. Redirects are still capped by
    urllib's own `max_repeats`/`max_redirections`."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # SSRF: never let a redirect send the request to a link-local / metadata target
        # (a common SSRF-via-redirect bypass). Abort → declare-unknown, no internal fetch.
        blocked = _ssrf_blocked_host(_hostname(newurl))
        if blocked:
            raise urllib.error.HTTPError(
                newurl, code, f"redirect to blocked address {blocked} (SSRF guard)",
                headers, fp)
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and _host(newurl) != _host(req.full_url):
            for h in ("Authorization", "Cookie"):
                new.headers.pop(h, None)
                new.unredirected_hdrs.pop(h, None)
        return new


# One opener reused for every http tool call — same-host redirects follow normally, a
# cross-host redirect drops the credential (INV-12). Built once at import (cheap).
_OPENER = urllib.request.build_opener(_NoAuthLeakRedirect())


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def exec_tool(spec: ToolSpec, request: Any, secret: str | None) -> ToolResult:
    """Execute one HTTP read. Returns a `ToolResult` (never raises for a call error).

    `request` (the body's `tool_request.args`, disposed by the runner):
      `{url: str, method?: "GET"|"HEAD", headers?: {str: str}, timeout?: int}`.
    `secret` is the pre-resolved credential (or None) — the runner resolved
    `spec.credential_ref` in memory; this adapter injects it as a Bearer token when
    present and no explicit Authorization header was given. The token NEVER appears
    in the ToolResult (INV-12 — only the response does).
    """
    tid = spec.tool_id
    if not isinstance(request, dict):
        return ToolResult.unknown(tid, "http request must be a mapping with a 'url'")
    url = request.get("url")
    if not isinstance(url, str) or not url.strip():
        return ToolResult.unknown(tid, "http request needs a non-empty 'url'")
    url = url.strip()
    scheme = url.split("://", 1)[0].lower() if "://" in url else ""
    if scheme not in _ALLOWED_SCHEMES:
        return ToolResult.unknown(
            tid, f"http url must be http/https, got scheme {scheme!r}")

    # SSRF guard (INV-10 defence-in-depth): refuse a body-supplied URL that targets (or
    # resolves to) a link-local / cloud-metadata address before any network call.
    blocked = _ssrf_blocked_host(_hostname(url))
    if blocked:
        return ToolResult.unknown(
            tid, f"http url targets a blocked address {blocked!r} (link-local / "
            "cloud-metadata) — refusing (SSRF guard)")

    method = str(request.get("method", "GET")).upper()
    # Direction-gated verbs (INV-19/23): a read tool is GET/HEAD-only; an act tool also
    # reaches the write verbs. The gate keys on the SPEC's direction, never the request —
    # a body cannot upgrade a read tool to a write.
    allowed = _READ_METHODS | _WRITE_METHODS if spec.is_act else _READ_METHODS
    if method not in allowed:
        kind = "act" if spec.is_act else "read"
        return ToolResult.unknown(
            tid, f"http {kind} adapter allows only {sorted(allowed)}, got {method!r}")

    try:
        timeout = int(request.get("timeout", DEFAULT_TIMEOUT_SECONDS))
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT_SECONDS
    timeout = max(1, min(timeout, MAX_TIMEOUT_SECONDS))

    headers: dict[str, str] = {}
    raw_headers = request.get("headers")
    if isinstance(raw_headers, dict):
        for k, v in raw_headers.items():
            if isinstance(k, str) and isinstance(v, str):
                headers[k] = v
    # Credential host-pinning (INV-12) — the Bearer token is attached ONLY when the
    # request URL's host matches the tool's declared `base_host`. The URL is body-supplied
    # for a read tool, so without this a poisoned body could point a credential-bearing
    # tool at an attacker host and exfiltrate the token through this sanctioned channel
    # (the cross-host REDIRECT strip below does not cover a directly body-named host). A
    # credential-bearing tool that declares no host is REFUSED (fail-closed) rather than
    # leaked. No credential → no host constraint (a public-fetch tool may roam, budget-capped).
    if secret:
        allowed_host = spec.credential_host
        req_host = _host(url).lower()
        if not allowed_host:
            return ToolResult.unknown(
                tid, f"tool {tid!r} carries a credential but declares no base_host — "
                "refusing to attach the token (a credential-bearing tool MUST pin its host; "
                "add base_host to its Act Config). INV-12.")
        if req_host != allowed_host:
            return ToolResult.unknown(
                tid, f"tool {tid!r} may only send its credential to host {allowed_host!r}; "
                f"request host {req_host!r} is not allowed — token NOT sent (INV-12)")
        if not any(h.lower() == "authorization" for h in headers):
            headers["Authorization"] = f"Bearer {secret}"

    # A JSON body for a write verb (POST/PATCH/PUT). The body is the act payload the
    # deterministic writer computed (never a token — INV-12; the secret rides the
    # Authorization header only). Encoded UTF-8 with a JSON content-type when absent.
    body_bytes: bytes | None = None
    json_body = request.get("json")
    if json_body is not None and method in _WRITE_METHODS:
        try:
            body_bytes = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            return ToolResult.unknown(tid, f"http json body not serialisable: {exc}")
        if not any(h.lower() == "content-type" for h in headers):
            headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, method=method, headers=headers, data=body_bytes)
    # Retry a rate-limit / transient 5xx with bounded exponential backoff; honest-degrade
    # after MAX_RETRIES. The shared opener strips Authorization on a cross-host redirect
    # (INV-12) — NOT the module-level urlopen (which re-sends the Bearer token).
    raw = b""
    status_code: Any = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            with _OPENER.open(req, timeout=timeout) as resp:  # noqa: S310 (scheme gated above)
                status_code = getattr(resp, "status", None) or resp.getcode()
                raw = resp.read(MAX_RESPONSE_BYTES + 1)
            break
        except urllib.error.HTTPError as exc:
            if exc.code in _RETRYABLE_STATUS and attempt < MAX_RETRIES:
                _sleep(_retry_after_seconds(exc, attempt))
                continue
            retried = f" after {attempt} retr{'y' if attempt == 1 else 'ies'}" if attempt else ""
            return ToolResult.unknown(tid, f"http {exc.code} for {url}{retried}")
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            return ToolResult.unknown(tid, f"http request failed: {exc}")

    truncated = len(raw) > MAX_RESPONSE_BYTES
    body = raw[:MAX_RESPONSE_BYTES]
    try:
        text = body.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 — defensive; decode with replace never raises
        text = repr(body)
    note = " (truncated)" if truncated else ""
    return ToolResult(
        tool_id=tid,
        status="ok",
        data={"status_code": status_code, "body": text, "truncated": truncated},
        summary=f"http {status_code} {url} — {len(body)} bytes{note}",
        raw_hash=_hash(body),
        is_external=True,  # external-system content → firewall flag (INV-17)
    )
