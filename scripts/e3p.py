#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["typer", "rich"]
# ///
"""E3@NYCU (Moodle) atoms — login / whoami / courses / assignments / due / announcements / submission / grades / content / download / call.

Wraps the Moodle Web Services REST API (`/webservice/rest/server.php`) so
agents and humans can query an enrolled Moodle site without hand-rolling
form posts. Defaults target NYCU's E3 (`e3p.nycu.edu.tw`) but the base URL
is configurable for any Moodle 4.x install with the `moodle_mobile_app`
service enabled.

Authentication flow:
    `uv run scripts/e3p.py login` prompts for username/password, exchanges them via
    `/login/token.php`, and stores `{base, service, token, userid,
    username}` in `~/.config/nycu/e3p.json` (mode 0600). Subsequent atoms
    read it transparently. Env vars take precedence over the file so the
    same script works stateless in CI / agents.

Env knobs (all optional; legacy UTILS_E3P_* names remain accepted):
    NYCU_E3P_BASE     Moodle site root (default: https://e3p.nycu.edu.tw)
    NYCU_E3P_SERVICE  WS service name (default: moodle_mobile_app)
    NYCU_E3P_TOKEN    pre-shared token (skip login)
    NYCU_E3P_USERID   pre-shared userid (skip login)
    NYCU_E3P_CONFIG   override config file path
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

# Siblings shadow stdlib (json.py, uuid.py). Drop our dir off sys.path so
# typer/rich and urllib resolve the stdlib versions normally.
_sys.path[:] = [p for p in _sys.path if _Path(p).resolve() != _Path(__file__).resolve().parent]

# Add ../lib for shared output helpers (envelope, fail).
_LIB = str(_Path(__file__).resolve().parent.parent / "lib")
if _LIB not in _sys.path:
    _sys.path.insert(0, _LIB)

import html
import json
import os
import re
import ssl
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl
from urllib.request import Request, urlopen, build_opener, HTTPRedirectHandler, HTTPSHandler

# NYCU's e3p cert chain is missing the Subject Key Identifier extension, which
# Python 3.13+ rejects by default (VERIFY_X509_STRICT). curl works because it
# uses macOS's system trust store, which is more lenient. Build a context that
# keeps full verification but drops the strict-extension check.
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.verify_flags &= ~ssl.VERIFY_X509_STRICT

import typer
from rich.console import Console
from rich.table import Table

from _envelope import emit, fail  # noqa: E402
from _paths import config_path, setting  # noqa: E402

BASE_DEFAULT = "https://e3p.nycu.edu.tw"
SERVICE_DEFAULT = "moodle_mobile_app"

app = typer.Typer(
    rich_markup_mode=None,
    no_args_is_help=True,
    add_completion=False,
    help="E3@NYCU (Moodle) atoms — login / courses / assignments / due / announcements / submission / grades / content / download / call.",
)
console = Console()


# ── config / creds ──────────────────────────────────────────────
def _config_path() -> Path:
    return config_path("e3p")


def _save_creds(d: dict) -> None:
    p = _config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2))
    p.chmod(0o600)


def _load_creds() -> dict:
    # Env overrides file — lets agents inject creds without touching disk.
    if tok := setting("TOKEN"):
        return {
            "token": tok,
            "userid": int(setting("USERID", "0")) or None,
            "base": setting("BASE", BASE_DEFAULT).rstrip("/"),
            "service": setting("SERVICE", SERVICE_DEFAULT),
        }
    p = _config_path()
    if not p.exists():
        fail(
            "not logged in",
            why=f"no config at {p}",
            hint="run `uv run scripts/e3p.py login` to obtain a token",
        )
    return json.loads(p.read_text())


# ── HTTP / WS plumbing ──────────────────────────────────────────
def _post(url: str, data: dict) -> Any:
    body = urlencode(_flatten(data)).encode()
    req = Request(url, data=body, headers={"User-Agent": "utils-e3p/1.0"})
    try:
        with urlopen(req, timeout=30, context=_SSL_CTX) as resp:
            raw = resp.read()
    except HTTPError as e:
        fail("e3p HTTP error", why=f"{e.code} {e.reason}", hint=url)
    except URLError as e:
        fail("e3p network error", why=str(e), hint="check connectivity / base URL")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        fail(
            "e3p: non-JSON response",
            why=raw[:200].decode(errors="replace"),
            hint="usually an E3 login/maintenance page; run `e3p_whoami` to check the token",
        )


def _flatten(params: dict) -> list[tuple[str, str]]:
    """Serialize dict to Moodle's foo[0]=a&foo[1]=b style. None values dropped."""
    out: list[tuple[str, str]] = []
    for k, v in params.items():
        if v is None:
            continue
        if isinstance(v, list):
            for i, item in enumerate(v):
                out.append((f"{k}[{i}]", str(item)))
        elif isinstance(v, bool):
            out.append((k, "1" if v else "0"))
        else:
            out.append((k, str(v)))
    return out


def _ws(function: str, *, _creds: Optional[dict] = None, **params) -> Any:
    """Call a Moodle WS function. Raises via fail() on transport or WS errors."""
    creds = _creds or _load_creds()
    base = creds["base"].rstrip("/")
    url = f"{base}/webservice/rest/server.php"
    payload = {
        "wstoken": creds["token"],
        "wsfunction": function,
        "moodlewsrestformat": "json",
        **params,
    }
    result = _post(url, payload)
    if isinstance(result, dict) and "exception" in result:
        ec = result.get("errorcode", "?")
        msg = result.get("message", "")
        if ec in ("invalidtoken", "accessexception"):
            fail("invalid or expired token", why=msg, hint="run `uv run scripts/e3p.py login` to refresh")
        fail(
            f"e3p WS error: {ec}",
            why=msg,
            hint=f"'{function}' was rejected; check the id arguments, or that you are enrolled in that course",
        )
    return result


def _strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s or "")
    return html.unescape(s).strip()


def _fmt_ts(ts: Optional[int], fmt: str = "%Y-%m-%d %H:%M") -> str:
    if not ts:
        return "-"
    return datetime.fromtimestamp(int(ts)).strftime(fmt)


# ── login / logout / whoami ─────────────────────────────────────
@app.command(help="Exchange username/password for a WS token; store at ~/.config/nycu/e3p.json.")
def login(
    username: str = typer.Option(..., "--username", "-u", prompt=True, help="Moodle login (often student ID, not display username)"),
    password: str = typer.Option(..., "--password", "-p", prompt=True, hide_input=True),
    base: str = typer.Option(BASE_DEFAULT, "--base", help="Moodle site root"),
    service: str = typer.Option(SERVICE_DEFAULT, "--service", help="WS service shortname"),
) -> None:
    base = base.rstrip("/")
    result = _post(
        f"{base}/login/token.php",
        {"username": username, "password": password, "service": service},
    )
    if "error" in result:
        fail(
            "login failed",
            why=result.get("error", ""),
            hint=result.get("errorcode") or "if you use NYCU portal SSO, your username here is the student ID (the 9-digit number), not the portal display name",
        )
    token = result["token"]
    info = _ws(
        "core_webservice_get_site_info",
        _creds={"base": base, "token": token, "service": service, "userid": None},
    )
    creds = {
        "base": base,
        "service": service,
        "token": token,
        "userid": info["userid"],
        "username": info["username"],
    }
    _save_creds(creds)

    def human(d, _m):
        console.print(f"[green]✓[/] logged in as [bold]{info['fullname']}[/] ({d['username']}, uid {d['userid']})")
        console.print(f"  base: {d['base']}")
        console.print(f"  saved: {_config_path()}")

    emit({k: v for k, v in creds.items() if k != "token"} | {"fullname": info["fullname"]}, human=human)


@app.command(help="Forget the stored token / config file.")
def logout() -> None:
    p = _config_path()
    if p.exists():
        p.unlink()
        emit({"removed": str(p)}, human=lambda d, _m: console.print(f"[green]✓[/] removed {p}"))
    else:
        emit({"removed": None}, human=lambda d, _m: console.print("no creds stored"))


@app.command(help="Show the current authenticated user + site info.")
def whoami() -> None:
    info = _ws("core_webservice_get_site_info")
    out = {
        "userid": info["userid"],
        "username": info["username"],
        "fullname": info["fullname"],
        "siteurl": info["siteurl"],
        "lang": info.get("lang"),
        "release": info.get("release"),
    }

    def human(d, _m):
        console.print(f"[bold]{d['fullname']}[/]  ({d['username']}, uid {d['userid']})")
        console.print(f"site: {d['siteurl']}  release: {d.get('release','-')}")

    emit(out, human=human)


# ── courses ─────────────────────────────────────────────────────
@app.command(help="List enrolled courses (sorted by start date, newest first).")
def courses(
    show_hidden: bool = typer.Option(False, "--hidden", help="Include hidden / archived courses"),
) -> None:
    creds = _load_creds()
    if not creds.get("userid"):
        fail("missing userid", why="env-only creds without NYCU_E3P_USERID", hint="set NYCU_E3P_USERID or run `uv run scripts/e3p.py login`")
    data = _ws("core_enrol_get_users_courses", userid=creds["userid"], _creds=creds)
    if not show_hidden:
        data = [c for c in data if c.get("visible", 1)]
    data.sort(key=lambda c: c.get("startdate", 0), reverse=True)
    rows = [
        {
            "id": c["id"],
            "shortname": c["shortname"],
            "fullname": c["fullname"],
            "startdate": c.get("startdate"),
            "progress": c.get("progress"),
            # Moodle counts every active enrolment, so teachers and TAs are included.
            "enrolled": c.get("enrolledusercount"),
        }
        for c in data
    ]

    def human(d, _m):
        t = Table(show_header=True, header_style="bold")
        t.add_column("ID")
        t.add_column("Shortname")
        t.add_column("Fullname")
        t.add_column("Enrolled", justify="right")
        for c in d:
            t.add_row(str(c["id"]), c["shortname"], c["fullname"], "" if c["enrolled"] is None else str(c["enrolled"]))
        console.print(t)

    emit(rows, {"count": len(rows)}, human=human)


# ── assignments ─────────────────────────────────────────────────
@app.command(help="List assignments (one course or all enrolled). Use --status to include your submission state.")
def assignments(
    courseid: Optional[int] = typer.Argument(None, help="Course ID; omit for all enrolled"),
    status: bool = typer.Option(False, "--status/--no-status", help="Fetch your submission status per assignment (N+1 calls)"),
) -> None:
    creds = _load_creds()
    if courseid:
        course_ids = [courseid]
    else:
        if not creds.get("userid"):
            fail("missing userid", hint="set NYCU_E3P_USERID or run `uv run scripts/e3p.py login`")
        cs = _ws("core_enrol_get_users_courses", userid=creds["userid"], _creds=creds)
        course_ids = [c["id"] for c in cs]

    result = _ws("mod_assign_get_assignments", courseids=course_ids, _creds=creds)
    items: list[dict] = []
    for course in result.get("courses", []):
        for a in course.get("assignments", []):
            entry = {
                "courseid": course["id"],
                "course_shortname": course["shortname"],
                "assignid": a["id"],
                "cmid": a["cmid"],
                "name": a["name"],
                "duedate": a.get("duedate") or None,
                "cutoffdate": a.get("cutoffdate") or None,
                "allowsubmissionsfromdate": a.get("allowsubmissionsfromdate") or None,
                "intro": _strip_html(a.get("intro", "")),
                "attachments": [
                    {"name": f.get("filename"), "url": f.get("fileurl")}
                    for f in a.get("introattachments", [])
                ],
            }
            if status and creds.get("userid"):
                s = _ws("mod_assign_get_submission_status", assignid=a["id"], userid=creds["userid"], _creds=creds)
                sub = (s.get("lastattempt") or {}).get("submission") or {}
                entry["submission_status"] = sub.get("status")
                entry["grading_status"] = sub.get("gradingstatus")
                entry["timemodified"] = sub.get("timemodified")
            items.append(entry)

    items.sort(key=lambda x: x["duedate"] or 0)

    def human(d, _m):
        t = Table(show_header=True, header_style="bold")
        t.add_column("Course")
        t.add_column("ID", justify="right")
        t.add_column("Name")
        t.add_column("Due")
        if status:
            t.add_column("Status")
        for it in d:
            due = _fmt_ts(it["duedate"], "%m/%d %H:%M")
            row = [it["course_shortname"], str(it["assignid"]), it["name"], due]
            if status:
                s = it.get("submission_status") or "-"
                color = {"submitted": "green", "new": "red", "draft": "yellow"}.get(s, "white")
                row.append(f"[{color}]{s}[/]")
            t.add_row(*row)
        console.print(t)

    emit(items, {"count": len(items), "with_status": status}, human=human)


# ── due / upcoming ──────────────────────────────────────────────
@app.command(help="Upcoming action events (deadlines / quizzes / unsubmitted items) from your calendar.")
def due(
    days: int = typer.Option(14, "--days", "-d", help="Look ahead window"),
    limit: int = typer.Option(50, "--limit", "-n"),
) -> None:
    now = int(datetime.now().timestamp())
    later = now + days * 86400
    res = _ws(
        "core_calendar_get_action_events_by_timesort",
        timesortfrom=now,
        timesortto=later,
        limitnum=limit,
    )
    evs = res.get("events", [])
    rows = [
        {
            "name": e["name"],
            "timesort": e["timesort"],
            "course": (e.get("course") or {}).get("shortname"),
            "courseid": (e.get("course") or {}).get("id"),
            "url": e.get("url"),
            "modulename": e.get("modulename"),
            "instance": e.get("instance"),
        }
        for e in evs
    ]

    def human(d, _m):
        t = Table(show_header=True, header_style="bold")
        t.add_column("When")
        t.add_column("Course")
        t.add_column("Type")
        t.add_column("Event")
        for r in d:
            t.add_row(
                _fmt_ts(r["timesort"], "%m/%d %H:%M"),
                r.get("course") or "-",
                r.get("modulename") or "-",
                r["name"],
            )
        console.print(t)

    emit(rows, {"count": len(rows), "days": days}, human=human)


# ── submission ──────────────────────────────────────────────────
@app.command(help="Detailed submission status for one assignment (you, by assignid).")
def submission(assignid: int = typer.Argument(..., help="Assignment ID (from `assignments` output)")) -> None:
    creds = _load_creds()
    if not creds.get("userid"):
        fail("missing userid", hint="set NYCU_E3P_USERID or run `uv run scripts/e3p.py login`")
    s = _ws("mod_assign_get_submission_status", assignid=assignid, userid=creds["userid"], _creds=creds)
    last = s.get("lastattempt") or {}
    sub = last.get("submission") or {}
    files: list[dict] = []
    text: Optional[str] = None
    for plugin in sub.get("plugins", []):
        if plugin.get("type") == "file":
            for area in plugin.get("fileareas", []):
                for f in area.get("files", []):
                    files.append({
                        "name": f.get("filename"),
                        "size": f.get("filesize"),
                        "url": f.get("fileurl"),
                    })
        elif plugin.get("type") == "onlinetext":
            for area in plugin.get("editorfields", []):
                if txt := area.get("text"):
                    text = _strip_html(txt)

    fb = s.get("feedback") or {}
    grade_val = (fb.get("grade") or {}).get("grade")

    out = {
        "assignid": assignid,
        "status": sub.get("status"),
        "grading_status": sub.get("gradingstatus"),
        "timecreated": sub.get("timecreated"),
        "timemodified": sub.get("timemodified"),
        "can_edit": last.get("canedit"),
        "can_submit": last.get("cansubmit"),
        "graded": last.get("graded"),
        "files": files,
        "text": text,
        "grade": grade_val,
    }

    def human(d, _m):
        console.print(f"assign: [bold]{assignid}[/]   status: [bold]{d['status']}[/]   grading: {d['grading_status']}")
        if d.get("timemodified"):
            console.print(f"last modified: {_fmt_ts(d['timemodified'])}")
        for f in d.get("files", []):
            console.print(f"  📎 {f['name']}  {f['size']:,}b")
            console.print(f"     [dim]{f['url']}[/]")
        if d.get("text"):
            console.print(f"  text: {d['text'][:200]}")
        if d.get("grade") is not None:
            console.print(f"grade: [bold]{d['grade']}[/]")

    emit(out, human=human)


# ── grades ──────────────────────────────────────────────────────
@app.command(help="Your gradebook items for a course (or every enrolled course).")
def grades(
    courseid: Optional[int] = typer.Argument(None, help="Course ID; omit for all enrolled"),
) -> None:
    creds = _load_creds()
    if not creds.get("userid"):
        fail("missing userid", hint="set NYCU_E3P_USERID or run `uv run scripts/e3p.py login`")
    if courseid:
        ids = [courseid]
    else:
        cs = _ws("core_enrol_get_users_courses", userid=creds["userid"], _creds=creds)
        ids = [c["id"] for c in cs]
    out: list[dict] = []
    for cid in ids:
        r = _ws("gradereport_user_get_grade_items", courseid=cid, userid=creds["userid"], _creds=creds)
        for course in r.get("usergrades", []):
            for item in course.get("gradeitems", []):
                out.append({
                    "courseid": course["courseid"],
                    "item": item.get("itemname") or item.get("itemtype"),
                    "itemtype": item.get("itemtype"),
                    "grade": item.get("graderaw"),
                    "max": item.get("grademax"),
                    "percentage": item.get("percentageformatted"),
                    "feedback": _strip_html(item.get("feedback", "") or ""),
                })

    def human(d, _m):
        t = Table(show_header=True, header_style="bold")
        t.add_column("Course", justify="right")
        t.add_column("Item")
        t.add_column("Grade")
        t.add_column("Max")
        t.add_column("%")
        for r in d:
            g = "-" if r["grade"] is None else f"{r['grade']:g}"
            mx = "-" if r["max"] is None else f"{r['max']:g}"
            t.add_row(str(r["courseid"]), (r["item"] or "-")[:50], g, mx, r.get("percentage") or "-")
        console.print(t)

    emit(out, {"count": len(out)}, human=human)


# ── content ─────────────────────────────────────────────────────
@app.command(help="Course outline — sections and the activities (assigns / quizzes / pages / resources) inside.")
def content(courseid: int = typer.Argument(...)) -> None:
    sections = _ws("core_course_get_contents", courseid=courseid)
    out: list[dict] = []
    for sec in sections:
        for m in sec.get("modules", []):
            out.append({
                "section": sec.get("name"),
                "modname": m.get("modname"),
                "name": m.get("name"),
                "cmid": m.get("id"),
                "instance": m.get("instance"),
                "url": m.get("url"),
            })

    def human(d, _m):
        t = Table(show_header=True, header_style="bold")
        t.add_column("Type")
        t.add_column("Section")
        t.add_column("Name")
        t.add_column("ID", justify="right")
        for r in d:
            t.add_row(r["modname"] or "-", (r["section"] or "-")[:30], r["name"], str(r["instance"] or ""))
        console.print(t)

    emit(out, {"count": len(out), "courseid": courseid}, human=human)


# ── announcements ───────────────────────────────────────────────
def _html_to_text(s: str) -> str:
    """Keep line breaks from block tags so a post reads as paragraphs, not one run-on line."""
    s = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr)>", "\n", s or "")
    s = html.unescape(re.sub(r"<[^>]+>", "", s)).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in s.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


@app.command(help="Recent posts in each course's announcements forum (Moodle news forum), newest first.")
def announcements(
    courseid: Optional[int] = typer.Argument(None, help="Course ID; omit for all visible enrolled courses"),
    days: int = typer.Option(30, "--days", "-d", help="Look back window"),
    limit: int = typer.Option(20, "--limit", "-n", help="Maximum posts per course"),
) -> None:
    creds = _load_creds()
    if courseid:
        course_ids = [courseid]
    else:
        if not creds.get("userid"):
            fail("missing userid", hint="set NYCU_E3P_USERID or run `uv run scripts/e3p.py login`")
        cs = _ws("core_enrol_get_users_courses", userid=creds["userid"], _creds=creds)
        course_ids = [c["id"] for c in cs if c.get("visible", 1)]
    if not course_ids:
        emit([], {"count": 0, "days": days}, human=lambda d, _m: console.print("no courses"))
        return

    forums = _ws("mod_forum_get_forums_by_courses", courseids=course_ids, _creds=creds)
    since = int(datetime.now().timestamp()) - days * 86400
    rows: list[dict] = []
    for f in forums:
        if f.get("type") != "news":
            continue
        res = _ws("mod_forum_get_forum_discussions", forumid=f["id"], sortorder=1, page=0, perpage=limit, _creds=creds)
        for x in res.get("discussions", []):
            # Pinned posts sort first regardless of age, so filter rather than stop early.
            posted = x.get("created") or x.get("timemodified") or 0
            if posted < since:
                continue
            rows.append({
                "courseid": f["course"],
                "forumid": f["id"],
                "discussionid": x.get("discussion"),
                "subject": x.get("subject") or x.get("name"),
                "author": x.get("userfullname"),
                "created": posted,
                "pinned": bool(x.get("pinned")),
                "message": _html_to_text(x.get("message", "")),
                "attachments": [
                    {"name": a.get("filename"), "url": a.get("fileurl")}
                    for a in (x.get("attachments") or [])
                ],
                "url": f"{creds['base'].rstrip('/')}/mod/forum/discuss.php?d={x.get('discussion')}",
            })
    rows.sort(key=lambda r: r["created"], reverse=True)

    def human(d, _m):
        t = Table(show_header=True, header_style="bold")
        t.add_column("Posted")
        t.add_column("Course", justify="right")
        t.add_column("Subject")
        t.add_column("Author")
        for r in d:
            t.add_row(_fmt_ts(r["created"], "%m/%d %H:%M"), str(r["courseid"]), r["subject"] or "-", r["author"] or "-")
        console.print(t)

    emit(rows, {"count": len(rows), "days": days}, human=human)


# ── download ────────────────────────────────────────────────────
def _validate_download_url(url: str, base: str) -> None:
    candidate, site = urlsplit(url), urlsplit(base)
    if (candidate.scheme != "https" or candidate.username or candidate.password
            or (candidate.hostname, candidate.port or 443) != (site.hostname, site.port or 443)):
        raise ValueError("Download URL must use the configured Moodle HTTPS origin")
    if not re.search(r"/pluginfile\.php(?:/|$)", candidate.path):
        raise ValueError("Download URL must be a Moodle pluginfile.php URL")


class _DownloadRedirect(HTTPRedirectHandler):
    def __init__(self, base: str):
        self.base = base

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_download_url(newurl, self.base)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


@app.command(help="Download a Moodle pluginfile URL (auto-injects your token).")
def download(
    url: str = typer.Argument(..., help="https://.../webservice/pluginfile.php/... URL"),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Output path (default: basename)"),
) -> None:
    creds = _load_creds()
    try:
        _validate_download_url(url, creds["base"])
    except ValueError:
        fail("invalid download URL", hint="Use an HTTPS pluginfile.php URL from e3p_get_content on the configured Moodle site.")
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "token"]
    full = urlunsplit(parts._replace(query=urlencode(query + [("token", creds["token"])]), fragment=""))
    target = out or Path(parts.path.rsplit("/", 1)[-1])
    try:
        opener = build_opener(HTTPSHandler(context=_SSL_CTX), _DownloadRedirect(creds["base"]))
        with opener.open(Request(full, headers={"User-Agent": "nycu-e3p/1.0"}), timeout=60) as resp:
            target.write_bytes(resp.read())
    except (HTTPError, URLError, ValueError) as e:
        # URL and exception text can contain the injected token. Neither is public output.
        fail("download failed", why=f"HTTP {e.code}" if isinstance(e, HTTPError) else "Network failure or unsupported redirect",
             hint="Check connectivity, the configured Moodle site and file access permissions.")
    size = target.stat().st_size
    emit(
        {"path": str(target), "size": size},
        human=lambda d, _m: console.print(f"[green]✓[/] {d['path']} ({d['size']:,}b)"),
    )


# ── call (escape hatch) ─────────────────────────────────────────
@app.command(help="Call any Moodle WS function. Params as key=value (use key[]=v for lists).")
def call(
    function: str = typer.Argument(..., help="e.g. core_webservice_get_site_info"),
    params: list[str] = typer.Argument(None, help="key=value pairs; repeat key[]=v for arrays"),
) -> None:
    parsed: dict[str, Any] = {}
    for kv in params or []:
        if "=" not in kv:
            fail("bad param", why=kv, hint="use key=value")
        k, _, v = kv.partition("=")
        if k.endswith("[]"):
            parsed.setdefault(k[:-2], []).append(v)
        else:
            parsed[k] = v
    result = _ws(function, **parsed)
    emit(result, {"function": function})


if __name__ == "__main__":
    app()
