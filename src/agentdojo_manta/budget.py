"""Shared request reservations for the official DeepSeek Flash endpoint.

Peak prices checked 2026-10-18 at https://api-docs.deepseek.com/quick_start/pricing/.
This is conservative accounting, not an invoice: cache discounts and off-peak
discounts are ignored. Unreturned requests retain their full reservation.
"""
from __future__ import annotations

import os
import sqlite3
import time
import uuid
from decimal import Decimal
from contextlib import contextmanager
from pathlib import Path


class BudgetExceeded(RuntimeError):
    pass


class RequestBudget:
    INPUT_RATE = 300   # nanodollars per token = $0.30 / million
    OUTPUT_RATE = 1200  # $1.20 / million
    MAX_INPUT = 1_048_576
    MAX_OUTPUT = 393_216
    MODELS = {"deepseek-v4-flash", "deepseek-v4-flash-vision-exp", "deepseek-flash"}

    def __init__(self, path: str | Path, limit: str):
        self.path = str(path)
        self.limit = int(Decimal(limit) * 1_000_000_000)
        if self.limit <= 0:
            raise ValueError("V1_MAX_COST_USD must be positive")
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, amount INTEGER, state TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
            db.execute("INSERT OR IGNORE INTO settings VALUES ('blocked', '0')")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=60)
        try:
            with db:
                yield db
        finally:
            db.close()

    def reserve(self, model: str, max_output: int) -> str:
        if model not in self.MODELS or not 1 <= max_output <= self.MAX_OUTPUT:
            raise ValueError("Budget prices support only verified DeepSeek Flash models/output limits")
        amount = self.MAX_INPUT * self.INPUT_RATE + max_output * self.OUTPUT_RATE
        while True:
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                total = db.execute("SELECT COALESCE(SUM(amount), 0) FROM requests").fetchone()[0]
                pending = db.execute("SELECT COUNT(*) FROM requests WHERE state='pending'").fetchone()[0]
                if total + amount <= self.limit:
                    request_id = uuid.uuid4().hex
                    db.execute("INSERT INTO requests VALUES (?, ?, 'pending')", (request_id, amount))
                    return request_id
                if total - db.execute("SELECT COALESCE(SUM(amount),0) FROM requests WHERE state='pending'").fetchone()[0] + amount > self.limit or not pending:
                    db.execute("UPDATE settings SET value='1' WHERE key='blocked'")
                    # Commit the stop flag before raising outside the transaction.
                    blocked = True
                else:
                    blocked = False
            if blocked:
                raise BudgetExceeded("Insufficient budget for conservative next-request reservation; resume after increasing the cap")
            time.sleep(0.25)

    def settle(self, request_id: str, usage) -> float | None:
        prompt = getattr(usage, "prompt_tokens", None)
        output = getattr(usage, "completion_tokens", None)
        if not isinstance(prompt, int) or not isinstance(output, int):
            self.uncertain(request_id)
            return None
        amount = prompt * self.INPUT_RATE + output * self.OUTPUT_RATE
        with self.connect() as db:
            db.execute("UPDATE requests SET amount=?, state='settled' WHERE id=?", (amount, request_id))
        return amount / 1_000_000_000

    def uncertain(self, request_id: str):
        with self.connect() as db:
            db.execute("UPDATE requests SET state='uncertain' WHERE id=?", (request_id,))

    def snapshot(self):
        with self.connect() as db:
            rows = dict(db.execute("SELECT state, SUM(amount) FROM requests GROUP BY state"))
            blocked = db.execute("SELECT value FROM settings WHERE key='blocked'").fetchone()[0] == "1"
        return {"cap_usd": self.limit / 1_000_000_000,
                "accounted_upper_bound_usd": sum(rows.values()) / 1_000_000_000,
                "response_cost_upper_bound_usd": rows.get("settled", 0) / 1_000_000_000,
                "unreturned_reservations_usd": (rows.get("pending", 0) + rows.get("uncertain", 0)) / 1_000_000_000,
                "blocked": blocked, "invoice_cost_usd": None}


def configured_budget() -> RequestBudget | None:
    path = os.getenv("V1_BUDGET_DB")
    return RequestBudget(path, os.environ["V1_MAX_COST_USD"]) if path else None
