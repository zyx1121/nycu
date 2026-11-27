#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["typer", "rich", "playwright>=1.57"]
# ///
"""NYCU payment inquiry atom: what the university paid you, and why.

Wraps the cashier's payment inquiry system (pisystem.nycu.edu.tw), reached
through the shared portal SSO layer in `lib/_nycu_portal.py`. The system signs
in with its own JavaScript, so the portal's sign-in form is posted from
headless Chromium; the query then runs through the page's own data service.

Two kinds of payment come back:
- `cashier`: reimbursements and other payments, each with the voucher's memo.
- `salary`: payroll batches, each with the payroll name.

Read-only. Works off campus.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_sys.path[:] = [p for p in _sys.path if _Path(p).resolve() != _Path(__file__).resolve().parent]

_LIB = str(_Path(__file__).resolve().parent.parent / "lib")
if _LIB not in _sys.path:
    _sys.path.insert(0, _LIB)

import datetime as _dt
import html
import re
from typing import Any, Optional

import typer
from rich.console import Console
from rich.table import Table

from _envelope import emit, fail  # noqa: E402
from _nycu_portal import PortalError, relay_form  # noqa: E402

app = typer.Typer(
    rich_markup_mode=None,
    no_args_is_help=True,
    add_completion=False,
    help="NYCU payment inquiry atom: payments and salaries the university paid you.",
)
console = Console()


@app.callback()
def _main() -> None:
    """Keeps `list` a subcommand: Typer runs a lone command as the whole app."""

SYS_DIRECT = "ympcs"
ORIGIN = "https://pisystem.nycu.edu.tw"
SERVICE = "services/PAYLIST.ashx"
# The data service's function per payment kind. The page calls these two for students.
KINDS = {"CASHNET": "cashier", "PAYNET": "salary"}


def roc(day: _dt.date) -> str:
    """2026-01-05 -> 1150105, the 7 digit Republic of China date the system takes."""
    return f"{day.year - 1911:03d}{day.month:02d}{day.day:02d}"


def from_roc(value: Any) -> Optional[str]:
    """1150105 -> 2026-01-05. Anything else -> None."""
    m = re.fullmatch(r"(\d{3})(\d{2})(\d{2})", str(value or "").strip())
    if not m:
        return None
    try:
        return _dt.date(int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


def _amount(value: Any) -> Optional[int]:
    try:
        return round(float(value))
    except (TypeError, ValueError):
        return None


def _last4(value: Any) -> Optional[str]:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[-4:] if digits else None


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def parse_cashier(rows: list[dict]) -> list[dict]:
    """Cashier rows -> payments. Keeps only what a person needs: never the ID number or the full account."""
    out = []
    for r in rows:
        out.append({
            "kind": "cashier",
            "date": from_roc(r.get("PAYDATE")),
            "amount": _amount(r.get("TSAMT") if r.get("TSAMT") is not None else r.get("TSAMOUNT")),
            "net": _amount(r.get("NETPAY")),
            "tax": _amount(r.get("INCOMETAX")),
            "memo": _text(r.get("TSMEMO")),
            "bank": _text(r.get("BANKNAME")) or None,
            "account_last4": _last4(r.get("ACCNO")),
            "voucher": _text(r.get("TSNO")) or None,
            "department": _text(r.get("APYDEPNM") or r.get("DEPTNAME")) or None,
        })
    return out


def parse_salary(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        out.append({
            "kind": "salary",
            "date": from_roc(r.get("DBK")),
            "amount": _amount(r.get("TNTOL")),
            "net": _amount(r.get("TNTOL")),
            "tax": None,
            "memo": _text(r.get("PAYNAME")),
            "bank": None,
            "account_last4": None,
            "voucher": _text(r.get("PAYCODE")) or None,
            "department": None,
        })
    return out


def parse(responses: dict[str, Any]) -> list[dict]:
    """The page's data responses, keyed by function name -> payments sorted by date."""
    cashier = responses.get("CASHNET")
    if isinstance(cashier, dict):
        cashier = cashier.get("list_Tsl") or cashier.get("rows") or []
    salary = responses.get("PAYNET")
    if isinstance(salary, dict):
        salary = salary.get("rows") or []
    payments = parse_cashier(cashier or []) + parse_salary(salary or [])
    return sorted(payments, key=lambda p: (p["date"] or "", p["kind"], p["amount"] or 0))


def fetch(start: _dt.date, end: _dt.date, tries: int = 3) -> dict[str, Any]:
    """Sign in and query; the system sometimes stalls at sign-in or answers 500, so try again."""
    for attempt in range(tries):
        try:
            return _fetch_once(start, end)
        except PortalError as e:
            if attempt == tries - 1 or e.message in ("playwright is not installed", "Chromium is not installed"):
                raise
    raise AssertionError("unreachable")


def _fetch_once(start: _dt.date, end: _dt.date) -> dict[str, Any]:
    """Sign in through the portal in headless Chromium and return the data service's responses."""
    action, fields = relay_form(SYS_DIRECT)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise PortalError("playwright is not installed", why=str(e), hint="call `nycu_setup` to install Chromium") from e

    inputs = "".join(f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">' for k, v in fields.items())
    responses: dict[str, Any] = {}
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as e:
            raise PortalError("Chromium is not installed", why=str(e)[:300], hint="call `nycu_setup` to install Chromium") from e
        try:
            page = browser.new_page(locale="zh-TW")
            page.set_content(f'<form id="f" method="post" action="{html.escape(action)}">{inputs}</form>')
            with page.expect_navigation(timeout=60000):
                page.evaluate("document.getElementById('f').submit()")
            # The landing page signs in with its own script, then moves on to the payment list.
            page.wait_for_url(re.compile(r"PayList\.aspx", re.IGNORECASE), timeout=30000)
            page.wait_for_load_state("networkidle")

            page.fill("#SDATE", roc(start))
            page.fill("#EDATE", roc(end))
            # The query form packs its fields the way the data service reads them.
            filters = page.evaluate("JSON.stringify(AifGetPackage('#TB_F'))")
            for func in KINDS:
                res = page.request.post(
                    f"{ORIGIN}/{SERVICE}",
                    form={"funcName": func, "FilterData": filters, "_search": "false", "rows": "1000", "page": "1", "sord": "asc"},
                    timeout=60000,
                )
                if not res.ok:
                    raise PortalError(f"payment inquiry answered {res.status} for {KINDS[func]}", hint="the system is flaky; try again")
                responses[func] = res.json()
        except PortalError:
            raise
        except Exception as e:
            raise PortalError(
                "payment inquiry did not load",
                why=f"stopped at {page.url}: {str(e)[:300]}",
                hint="the system may be down, or its page changed; open https://pisystem.nycu.edu.tw to check",
            ) from e
        finally:
            browser.close()
    return responses


def _date(value: Optional[str], default: _dt.date, name: str) -> _dt.date:
    if not value:
        return default
    try:
        return _dt.date.fromisoformat(value)
    except ValueError:
        fail(f"{name} must be YYYY-MM-DD", why=f"got {value!r}")


@app.command(name="list", help="List payments and salaries the university paid you between two dates.")
def list_payments(
    start: Optional[str] = typer.Option(None, "--from", help="First day, YYYY-MM-DD. Default: January 1 of this year."),
    end: Optional[str] = typer.Option(None, "--to", help="Last day, YYYY-MM-DD. Default: today."),
    kind: Optional[str] = typer.Option(None, "--kind", help="cashier or salary. Default: both."),
) -> None:
    today = _dt.date.today()
    first = _date(start, today.replace(month=1, day=1), "--from")
    last = _date(end, today, "--to")
    if first > last:
        fail("--from is after --to", why=f"{first} > {last}")
    if kind not in (None, "cashier", "salary"):
        fail("--kind must be cashier or salary", why=f"got {kind!r}")
    try:
        payments = parse(fetch(first, last))
    except PortalError as e:
        fail(e.message, why=e.why, hint=e.hint)
    if kind:
        payments = [p for p in payments if p["kind"] == kind]
    totals = {k: sum(p["net"] or 0 for p in payments if p["kind"] == k) for k in ("cashier", "salary")}

    def human(d: list[dict], m: dict) -> None:
        t = Table(show_header=True, header_style="bold")
        for col in ("Date", "Kind", "Net", "Bank", "Memo"):
            t.add_column(col)
        for p in d:
            t.add_row(p["date"] or "-", p["kind"], f"{p['net']:,}" if p["net"] is not None else "-", p["bank"] or "-", p["memo"][:60])
        console.print(t)
        console.print(f"{m['count']} payments, cashier {m['totals']['cashier']:,}, salary {m['totals']['salary']:,}")

    emit(payments, {"from": first.isoformat(), "to": last.isoformat(), "count": len(payments), "totals": totals}, human=human)


if __name__ == "__main__":
    app()
