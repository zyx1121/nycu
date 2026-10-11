#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["typer", "rich", "playwright>=1.57"]
# ///
"""NYCU portal atoms — setup / whoami / systems / events / login / logout.

Wraps the NYCU portal (portal.nycu.edu.tw), the SSO layer sitting in front of
every NYCU web service. Login is reCAPTCHA v3 protected server-side, so it
goes through headless Chromium once (`nycu login` or the first read of any
atom), then every other command reuses the cached JWT from
`~/.config/utils/nycu.json`. Other portal-backed services (e.g. `parttime.py`)
build on the same shared layer in `lib/_nycu_portal.py`.

Creds come from macOS Keychain:
  service kilo/nycu-portal  account=<student id>  password=<portal password>
  service kilo/nycu-totp    account=<student id>  password=<otpauth://totp/... URI>
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

# Siblings shadow stdlib (json.py). Drop our dir off sys.path so typer/rich
# and urllib resolve the stdlib versions normally.
_sys.path[:] = [p for p in _sys.path if _Path(p).resolve() != _Path(__file__).resolve().parent]

# Add ../lib for shared output helpers (envelope, fail) and the portal layer.
_LIB = str(_Path(__file__).resolve().parent.parent / "lib")
if _LIB not in _sys.path:
    _sys.path.insert(0, _LIB)

import json as _json
import subprocess
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from _envelope import emit, fail  # noqa: E402
from _nycu_portal import PortalError, _config_path, api, last_call_relogged, logout as _logout, token  # noqa: E402

app = typer.Typer(
    rich_markup_mode=None,
    no_args_is_help=True,
    add_completion=False,
    help="NYCU portal atoms — setup / whoami / systems / events / login / logout.",
)
console = Console()


def _fail_from(e: PortalError) -> None:
    fail(e.message, why=e.why, hint=e.hint)


@app.command(help="Install the headless Chromium build Playwright needs for portal login.")
def setup() -> None:
    result = subprocess.run(
        [_sys.executable, "-m", "playwright", "install", "chromium"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        fail(
            "chromium install failed",
            why=(result.stderr or result.stdout)[-500:],
            hint="check network access to the Playwright CDN, or run the same command by hand to see the full log",
        )
    browser_path: Optional[str] = None
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser_path = p.chromium.executable_path
    except Exception:
        pass
    emit(
        {"installed": True, "browser_path": browser_path},
        {"log": result.stdout[-500:]},
        human=lambda d, _m: console.print(f"[green]✓[/] Chromium installed for portal login ({d['browser_path'] or 'path unknown'})"),
    )


@app.command(help="Show the authenticated portal user. Logs in via headless Chromium if no cached token exists.")
def whoami() -> None:
    try:
        _tok, source = token()
        st = api("getUserStatus")
    except PortalError as e:
        _fail_from(e)
        return
    if last_call_relogged():
        # The cached token looked fine but the server had already expired it;
        # api() silently re-logged in mid-call, so the token actually used
        # was fresh, not the cache hit `token()` reported a moment ago.
        source = "login"
    out = {k: v for k, v in st.items() if k != "token"}

    def human(d: dict, _m: dict) -> None:
        console.print(f"[bold]{d.get('name')}[/]  ({d.get('id')})")
        console.print(f"dept: {d.get('dept')}   mail: {d.get('mail')}")
        console.print(f"ou: {d.get('ou')}   area: {d.get('area')}   status: {d.get('idStatus')}")

    emit(out, {"source": source}, human=human)


@app.command(help="List portal sub-systems (getSyslink). Use --query to filter by name/direct.")
def systems(
    query: Optional[str] = typer.Option(None, "--query", help="Case-insensitive substring match on name/name_en/direct."),
) -> None:
    try:
        sl = api("getSyslink")
    except PortalError as e:
        _fail_from(e)
        return
    rows = [
        {
            "no": s.get("sysNo"),
            "name": s.get("sysName"),
            "name_en": s.get("sysEName"),
            "direct": s.get("sysDirect"),
            "url": s.get("sysURL"),
            "school_ip_only": s.get("requireSchoolIp") == "Y",
        }
        for s in sl.get("syslink", [])
    ]
    if query:
        q = query.lower()
        rows = [r for r in rows if q in (r["name"] or "").lower() or q in (r["name_en"] or "").lower() or q in (r["direct"] or "").lower()]

    def human(d: list[dict], _m: dict) -> None:
        t = Table(show_header=True, header_style="bold")
        t.add_column("No")
        t.add_column("Name")
        t.add_column("Direct")
        t.add_column("Campus IP only")
        for r in d:
            t.add_row(str(r["no"]), r["name"] or "-", r["direct"] or "-", "yes" if r["school_ip_only"] else "no")
        console.print(t)

    emit(rows, {"count": len(rows), "query": query}, human=human)


@app.command(help="List upcoming portal events (getUserEvents).")
def events() -> None:
    try:
        ev = api("getUserEvents")
    except PortalError as e:
        _fail_from(e)
        return
    rows = ev.get("events", [])

    def human(d: list[dict], _m: dict) -> None:
        if not d:
            console.print("no events")
            return
        for e in d:
            console.print(f"- {e}")

    emit(rows, {"count": len(rows)}, human=human)


@app.command(help="Refresh the cached JWT. Without --force, reuses a still-valid cached token; with --force, always logs in again.")
def login(
    force: bool = typer.Option(False, "--force", help="Re-login even if a cached token exists."),
) -> None:
    try:
        token(force=force)
    except PortalError as e:
        _fail_from(e)
        return
    saved = _json.loads(_config_path().read_text())

    def human(d: dict, _m: dict) -> None:
        console.print(f"[green]✓[/] logged in as {d['account']}")
        console.print(f"  obtained_at: {d['obtained_at']}")

    emit({"account": saved.get("account"), "obtained_at": saved.get("obtained_at")}, human=human)


@app.command(help="Forget the cached JWT (Keychain items are untouched). Destructive: requires --yes.")
def logout(
    yes: bool = typer.Option(False, "--yes", help="Required explicit confirmation."),
) -> None:
    if not yes:
        fail("refusing to log out without confirmation", hint="pass --yes to confirm")
    removed = _logout()
    emit(
        {"removed": removed},
        human=lambda d, _m: console.print(f"[green]✓[/] removed {d['removed']}" if d["removed"] else "no cached token"),
    )


if __name__ == "__main__":
    app()
