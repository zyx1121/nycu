#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["typer", "rich", "playwright>=1.57"]
# ///
"""Offline self-check for scripts/payments.py's parsing.

No network and no login: loads payments.py as a module and feeds its parser
made-up responses shaped like the payment inquiry system's data service.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("payments", ROOT / "scripts" / "payments.py")
payments = importlib.util.module_from_spec(spec)
sys.modules["payments"] = payments
spec.loader.exec_module(payments)  # type: ignore[union-attr]

failures: list[str] = []
total = 0


def check(name: str, condition: bool) -> None:
    global total
    total += 1
    print(f"[{'ok' if condition else 'FAIL'}] {name}")
    if not condition:
        failures.append(name)


check("roc date out", payments.roc(dt.date(2026, 1, 5)) == "1150105")
check("roc date in", payments.from_roc("1151125") == "2026-11-25")
check("bad roc date is None", payments.from_roc("1151340") is None and payments.from_roc("") is None)

responses = {
    "CASHNET": {"list_Tsl": [
        {"PAYDATE": "1150920", "TSAMT": 8080.0, "NETPAY": 8080.0, "INCOMETAX": 0.0, "TSMEMO": "Meeting meals  ",
         "BANKNAME": "Example Bank", "ACCNO": "1234567890123", "IDNO": "A123456789", "TSNO": "V-1", "APYDEPNM": "Lab"},
    ]},
    "PAYNET": [
        {"DBFROM": "QPAY", "PAYNAME": "Example payroll   ", "PAYCODE": "Salary1 ", "IDNO": "A123456789", "TNTOL": 7778.0, "DBK": "1151020"},
    ],
}
rows = payments.parse(responses)
check("two payments, sorted by date", [r["date"] for r in rows] == ["2026-09-20", "2026-10-20"])
cashier, salary = rows
check("cashier amount and memo", cashier["kind"] == "cashier" and cashier["net"] == 8080 and cashier["memo"] == "Meeting meals")
check("only the account's last 4 digits", cashier["account_last4"] == "0123")
check("salary amount and name", salary["kind"] == "salary" and salary["amount"] == 7778 and salary["memo"] == "Example payroll")
check("no ID number in the output", "A123456789" not in json.dumps(rows))
check("empty responses give no payments", payments.parse({}) == [])

print(f"\n{total - len(failures)}/{total} passed")
sys.exit(1 if failures else 0)
