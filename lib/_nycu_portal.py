"""Shared NYCU portal SSO layer for scripts/nycu.py and parttime.py.

Handles the reCAPTCHA-protected portal login (headless Chromium via
Playwright), JWT caching, the portal's form-encoded JSON API, and the
relay hop into a sub-system (e.g. the parttime timeclock).

Playwright is only imported inside `login()`, so importing this module
(and every read that hits the token cache) never pays its import cost.

Never let a portal password reach a log line, exception message, or the
JSON envelope: `login()` scrubs it out of any raised `PortalError.why`.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import http.cookiejar
import json
import os
import re
import ssl
import subprocess
import time
from _paths import config_path
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import HTTPCookieProcessor, HTTPSHandler, Request, build_opener, urlopen

API = "https://portal.nycu.edu.tw/portal/api/"
PORTAL_ORIGIN = "https://portal.nycu.edu.tw"

# NYCU's cert chain lacks the Subject Key Identifier extension, which Python
# 3.13+ rejects under VERIFY_X509_STRICT. Keep full verification, drop only
# the strict-extension check (same fix as e3p.py / timetable.py).
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.verify_flags &= ~ssl.VERIFY_X509_STRICT


class PortalError(Exception):
    """Raised by every helper in this module instead of calling fail() directly.

    Scripts run on typer's main thread, so the caller converts this to
    `_envelope.fail(e.message, why=e.why, hint=e.hint)` at exactly one call
    site. Never construct one with a raw password in `why`.
    """

    def __init__(self, message: str, why: Optional[str] = None, hint: Optional[str] = None) -> None:
        super().__init__(message)
        self.message = message
        self.why = why
        self.hint = hint


_JWT_RE = re.compile(r"eyJ[A-Za-z0-9._-]{20,}")
_OTPAUTH_RE = re.compile(r"otpauth://\S+")


def scrub(text: Optional[str], *secrets: str) -> Optional[str]:
    """Redact secrets from text bound for a PortalError.why / error envelope.

    `secrets` are exact strings (e.g. the portal password) to blank out.
    JWTs and otpauth:// URIs are always redacted too, since page dumps
    (relay/postback HTML) can echo a hidden `jwt` input verbatim.
    """
    if not text:
        return text
    for s in secrets:
        if s:
            text = text.replace(s, "<pw>")
    text = _JWT_RE.sub("<jwt>", text)
    text = _OTPAUTH_RE.sub("<otpauth>", text)
    return text


# ── credentials ──────────────────────────────────────────────────
# Keychain services: the portal password and the otpauth:// TOTP URI, both
# with the student id as the account.
PORTAL_SERVICE = "kilo/nycu-portal"
TOTP_SERVICE = "kilo/nycu-totp"


def creds() -> tuple[str, str, str]:
    """Return (account, password, totp_uri) from macOS Keychain."""
    account, password = _keychain(PORTAL_SERVICE)
    _, totp_uri = _keychain(TOTP_SERVICE)
    return account, password, totp_uri


def _keychain(service: str) -> tuple[str, str]:
    out = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-g"],
        capture_output=True,
        text=True,
    )
    if out.returncode != 0:
        raise PortalError(
            "nycu credentials missing",
            why=f"keychain item '{service}' not found: {out.stderr.strip()}",
            hint=f"security add-generic-password -s {service} -a <student id> -w   (run in Terminal.app, not from Claude's `!` shell, which stores an empty value)",
        )
    acct = next(
        (line.split('"')[3] for line in out.stdout.splitlines() if line.strip().startswith('"acct"')),
        None,
    )
    pw_out = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-w"],
        capture_output=True,
        text=True,
    )
    if pw_out.returncode != 0 or acct is None:
        raise PortalError(
            "nycu credentials missing",
            why=f"keychain item '{service}' has no account or password",
            hint=f"security add-generic-password -s {service} -a <student id> -w   (run in Terminal.app, not from Claude's `!` shell, which stores an empty value)",
        )
    return acct, pw_out.stdout.strip()


def totp(uri: str) -> str:
    """RFC 6238 TOTP (SHA1, 30s step, 6 digits) from an otpauth://totp/... URI."""
    u = urlparse(uri.strip())
    secret = parse_qs(u.query)["secret"][0].strip().replace(" ", "").upper()
    secret += "=" * ((-len(secret)) % 8)
    key = base64.b32decode(secret, casefold=True)
    msg = (int(time.time()) // 30).to_bytes(8, "big")
    h = hmac.new(key, msg, hashlib.sha1).digest()
    o = h[-1] & 0x0F
    code = (((h[o] & 0x7F) << 24) | (h[o + 1] << 16) | (h[o + 2] << 8) | h[o + 3]) % 1_000_000
    return f"{code:06d}"


# ── login ────────────────────────────────────────────────────────
def login() -> str:
    """Log in through headless Chromium and return the portal JWT.

    reCAPTCHA v3 is checked server-side, so this must go through a real
    browser context; there is no pure-HTTP login path.
    """
    account, password, totp_uri = creds()
    try:
        from playwright.sync_api import expect, sync_playwright
    except ImportError as e:
        raise PortalError(
            "playwright is not installed",
            why=str(e),
            hint="call `nycu_setup` to install Chromium",
        ) from e

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception as e:
                raise PortalError(
                    "Chromium is not installed",
                    why=str(e),
                    hint="call `nycu_setup` to install Chromium",
                ) from e
            ctx = browser.new_context(locale="zh-TW")
            page = ctx.new_page()
            try:
                page.goto(f"{PORTAL_ORIGIN}/", timeout=60000)
                page.locator("#account").fill(account)
                page.locator("#password").fill(password)
                btn = page.locator('button[data-test="login-button"]')
                expect(btn).to_be_enabled(timeout=60000)
                btn.click()

                dialog = page.locator('div[role="dialog"][aria-label="二階段驗證"]')
                expired = page.locator('div[role="dialog"][aria-label="錯誤"]', has_text="密碼已到期")
                try:
                    expect(expired).to_be_visible(timeout=8000)
                    expired.get_by_role("button", name="確認").click()
                except AssertionError:
                    pass

                try:
                    expect(dialog).to_be_visible(timeout=30000)
                except AssertionError:
                    body = page.locator("body").inner_text()
                    raise PortalError(
                        "portal login did not reach the 2FA step",
                        why=scrub(body[:600], password),
                        hint="check the account/password in Keychain, or that the portal UI hasn't changed",
                    )

                dialog.locator("input.el-input__inner").first.fill(totp(totp_uri))
                dialog.get_by_role("button", name="確定").click()
                expect(dialog).to_be_hidden(timeout=60000)
                page.wait_for_timeout(1500)
                cookies = {c["name"]: c["value"] for c in ctx.cookies()}
            finally:
                browser.close()
    except PortalError:
        raise
    except Exception as e:
        raise PortalError(
            "portal login failed",
            why=scrub(str(e), password),
            hint="call `nycu_setup` to install Chromium, or check the account/password/TOTP secret in Keychain",
        ) from e

    tok = cookies.get("userToken")
    if not tok:
        raise PortalError(
            "portal login did not yield a token",
            why=f"no userToken cookie; cookies present: {sorted(cookies)}",
            hint="try again; if it persists, the portal UI may have changed",
        )
    return tok


# ── token cache ──────────────────────────────────────────────────
def _config_path() -> Path:
    return config_path("portal")


def _jwt_claims(tok: str) -> dict:
    try:
        payload = tok.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except Exception:
        return {}


def token(force: bool = False) -> tuple[str, str]:
    """Return (token, source) where source is 'cache' or 'login'."""
    p = _config_path()
    if not force and p.exists():
        try:
            cached = json.loads(p.read_text())
            if cached.get("token"):
                expires = _jwt_claims(cached["token"]).get("exp")
                if not isinstance(expires, (int, float)) or expires > time.time():
                    return cached["token"], "cache"
        except (json.JSONDecodeError, OSError):
            pass
    tok = login()
    _save_token(tok)
    return tok, "login"


def _save_token(tok: str) -> None:
    account, _, _ = creds()
    claims = _jwt_claims(tok)
    p = _config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "token": tok,
        "account": account,
        "iat": claims.get("iat"),
        "obtained_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }, ensure_ascii=False, indent=2))
    p.chmod(0o600)


def logout() -> Optional[str]:
    """Delete the cached token file. Keychain items are untouched. Returns the removed path, or None."""
    p = _config_path()
    if p.exists():
        p.unlink()
        return str(p)
    return None


# ── portal API ───────────────────────────────────────────────────
def _post_form_full(url: str, form: dict, opener=None) -> tuple[bytes, str]:
    """POST a form, return (body, final_url) — final_url follows redirects."""
    body = urlencode(form).encode()
    req = Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": PORTAL_ORIGIN,
            "Referer": f"{PORTAL_ORIGIN}/",
            "User-Agent": "utils-nycu/1.0",
        },
    )
    try:
        if opener is not None:
            with opener.open(req, timeout=30) as resp:
                return resp.read(), resp.geturl()
        with urlopen(req, timeout=30, context=_SSL_CTX) as resp:
            return resp.read(), resp.geturl()
    except HTTPError as e:
        return e.read(), e.geturl() if hasattr(e, "geturl") else url
    except URLError as e:
        raise PortalError("nycu portal unreachable", why=str(e), hint="check network or campus IP requirements") from e


def _post_form(url: str, form: dict, opener=None) -> bytes:
    body, _final_url = _post_form_full(url, form, opener=opener)
    return body


# Set when the most recent top-level api() call had to re-login mid-call
# (a cached token that the server no longer honoured). A caller that already
# read `token()` for its own "source" bookkeeping (e.g. nycu.py whoami) should
# check this afterwards and upgrade "cache" to "login" if it flipped true.
_relogged = False


def last_call_relogged() -> bool:
    return _relogged


def _token_expired(message: str) -> bool:
    message = message.lower()
    return "token auth failed" in message or "token timeout" in message


def api(path: str, *, _retried: bool = False, **form) -> dict:
    """Call a portal API endpoint. Re-logs-in once on an expired token."""
    global _relogged
    if not _retried:
        _relogged = False
    tok, _source = token()
    form["token"] = tok
    raw = _post_form(API + path, form)
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        raise PortalError(
            "nycu portal: non-JSON response",
            why=scrub(raw[:200].decode(errors="replace")),
            hint="the portal API shape may have changed",
        ) from None

    if isinstance(result, dict) and result.get("status") == "false":
        message = result.get("message", "")
        if _token_expired(message) and not _retried:
            _relogged = True
            login_tok = login()
            _save_token(login_tok)
            return api(path, _retried=True, **{k: v for k, v in form.items() if k != "token"})
        raise PortalError(f"nycu portal API rejected '{path}'", why=scrub(message), hint="check the arguments or refresh the portal session using scripts/nycu.py login --force")
    return result


# ── relay into a sub-system ──────────────────────────────────────
_FORM_RE = re.compile(r'<form[^>]*action="([^"]+)"[^>]*>(.*?)</form>', re.DOTALL | re.IGNORECASE)
_INPUT_RE = re.compile(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', re.IGNORECASE)


def relay(sys_direct: str, *, _retried: bool = False) -> tuple[Any, str, str]:
    """Relay through the portal into a sub-system.

    Returns (opener, landing_html, landing_url). `opener` carries the
    cookie jar so subsequent requests to the sub-system stay in-session.
    """
    link = api("getLoginLink", sysDirect=sys_direct)
    entries = link.get("syslink") or []
    if not entries:
        raise PortalError(
            f"no system found for sysDirect={sys_direct!r}",
            why=json.dumps(link, ensure_ascii=False)[:200],
            hint="call nycu_list_systems for the correct sysDirect value",
        )
    entry = entries[0]
    sys_url = entry.get("sysURL")
    if not sys_url:
        raise PortalError(f"system {sys_direct!r} has no sysURL", why=json.dumps(entry, ensure_ascii=False)[:200])

    tok, _source = token()
    jar = http.cookiejar.CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar), HTTPSHandler(context=_SSL_CTX))
    opener.addheaders = [("User-Agent", "utils-nycu/1.0")]

    relay_html = _post_form(f"{API}relay", {"token": tok, "url": sys_url, "sysDirect": sys_direct}, opener=opener).decode(errors="replace")
    if _token_expired(relay_html) and not _retried:
        token(force=True)
        return relay(sys_direct, _retried=True)
    match = _FORM_RE.search(relay_html)
    if not match and "vpn-required" in relay_html:
        raise PortalError(
            f"{sys_direct!r} requires a campus IP",
            why="portal answered vpn-required; this client is not on the NYCU network (140.113.x)",
            hint="connect from campus Wi-Fi, NYCU VPN, or route through pve on the tailnet, then retry",
        )
    if not match:
        raise PortalError(
            f"relay to {sys_direct!r} returned no form",
            why=scrub(relay_html[:300]),
            hint="check campus IP requirements, or that the token is still valid",
        )
    action, body = match.group(1), match.group(2)
    fields = {name: html.unescape(value) for name, value in _INPUT_RE.findall(body)}

    landing, landing_url = _post_form_full(action, fields, opener=opener)
    return opener, landing.decode(errors="replace"), landing_url


def opener_post(opener, url: str, form: dict) -> str:
    """POST a form through an existing relay session's cookie jar; returns the response body."""
    return _post_form(url, form, opener=opener).decode(errors="replace")
