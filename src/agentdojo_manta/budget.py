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
import json
import hashlib
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


def configured_budget(model: str | None = None) -> RequestBudget | None:
    if os.getenv("MANTA_PROVIDER", "deepseek") != "deepseek":
        path = os.getenv("GPT4O_BUDGET_DB")
        if not path:
            if os.getenv("MAS_DISABLE_LIVE_LLM") == "1":
                return None
            raise ValueError("GPT-4o requires a persistent request budget")
        return GPT4oBudget(path, os.environ["GPT4O_MAX_COST_USD"])
    path = os.getenv("V1_BUDGET_DB")
    if (model or os.getenv("DEEPSEEK_MODEL")) == "deepseek-v4-pro":
        if not path and os.getenv("MAS_DISABLE_LIVE_LLM") != "1":
            raise ValueError("DeepSeek Pro requires a persistent request budget")
        return DeepSeekProBudget(path, os.environ["V1_MAX_COST_USD"]) if path else None
    return RequestBudget(path, os.environ["V1_MAX_COST_USD"]) if path else None


class DeepSeekProBudget(RequestBudget):
    """Official peak, uncached prices verified 2026-10-28; discounts ignored."""
    INPUT_RATE = 1320
    OUTPUT_RATE = 3960
    MODELS = {"deepseek-v4-pro"}

    def __init__(self, path, limit):
        super().__init__(path, limit)
        identity = "deepseek:deepseek-v4-pro:1320:3960:1048576"
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT value FROM settings WHERE key='pricing_identity'").fetchone()
            if previous and previous[0] != identity:
                raise ValueError("Existing ledger belongs to a different model or price profile")
            if not previous and db.execute("SELECT COUNT(*) FROM requests").fetchone()[0]:
                raise ValueError("Cannot reuse a Flash/GPT-4o ledger for Pro")
            db.execute("INSERT OR IGNORE INTO settings VALUES ('pricing_identity', ?)", (identity,))


class GPT4oBudget(RequestBudget):
    """Independent GPT-4o accounting in nanodollars; ignores cache discounts."""

    INPUT_RATE = 2500
    OUTPUT_RATE = 10000
    MAX_INPUT = 128000
    MAX_OUTPUT = 16384
    MODELS = {"gpt-4o"}

    def __init__(self, path, limit):
        provider = os.getenv("MANTA_PROVIDER", "openai")
        multiplier = Decimal(os.getenv("GPT4O_PRICE_MULTIPLIER", "1"))
        if not multiplier.is_finite() or multiplier <= 0:
            raise ValueError("Invalid GPT-4o price multiplier")
        if provider == "qdd" and not os.getenv("GPT4O_PRICING_EVIDENCE"):
            raise ValueError("QDD requires verified account pricing evidence before paid calls")
        evidence_hash = None
        if provider == "qdd":
            evidence_bytes = Path(os.environ["GPT4O_PRICING_EVIDENCE"]).read_bytes()
            evidence = json.loads(evidence_bytes)
            evidence_hash = hashlib.sha256(evidence_bytes).hexdigest()
            sources = {r["path"]: r for r in evidence["sources"]}
            price = sources["/api/pricing"]
            billing = sources["/api/log/token"]
            if (evidence.get("endpoint") != "https://api2.aigcbest.top/v1" or
                    not sources["/v1/models"].get("gpt4o_visible") or
                    price.get("http_status") != 200 or billing.get("http_status") != 200 or
                    not price.get("gpt4o") or not billing.get("latest_gpt4o_billing")):
                raise ValueError("Incomplete GPT-4o route pricing evidence")
            public = price["gpt4o"][0]
            if public.get("model_ratio") != 1.25 or public.get("completion_ratio") != 4 or public.get("quota_type") != 0:
                raise ValueError("QDD published GPT-4o price has changed")
            for charge in billing["latest_gpt4o_billing"]:
                if (charge.get("model_ratio") != 1.25 or charge.get("completion_ratio") != 4 or
                        Decimal(str(charge.get("group_ratio"))) > multiplier or charge.get("user_group_ratio") not in (-1, None)):
                    raise ValueError("Configured rate does not bound observed token billing rates")
        self.INPUT_RATE = int(Decimal(2500) * multiplier)
        self.OUTPUT_RATE = int(Decimal(10000) * multiplier)
        if Decimal(self.INPUT_RATE) != 2500 * multiplier or Decimal(self.OUTPUT_RATE) != 10000 * multiplier:
            raise ValueError("Price multiplier exceeds nanodollar precision")
        super().__init__(path, limit)
        identity = f"{provider}:gpt-4o:{self.INPUT_RATE}:{self.OUTPUT_RATE}:{self.MAX_INPUT}"
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT value FROM settings WHERE key='pricing_identity'").fetchone()
            if existing and existing[0] != identity:
                raise ValueError("Cannot change provider/prices in an existing GPT-4o ledger")
            if not existing and db.execute("SELECT COUNT(*) FROM requests").fetchone()[0]:
                raise ValueError("Cannot reuse a non-GPT-4o budget ledger")
            db.execute("INSERT OR IGNORE INTO settings VALUES ('pricing_identity', ?)", (identity,))
            if evidence_hash:
                existing_evidence = db.execute("SELECT value FROM settings WHERE key='pricing_evidence_sha256'").fetchone()
                if existing_evidence and existing_evidence[0] != evidence_hash:
                    raise ValueError("Pricing evidence changed; preserve the existing run")
                db.execute("INSERT OR IGNORE INTO settings VALUES ('pricing_evidence_sha256', ?)", (evidence_hash,))

    def reserve(self, model, max_output):
        if model != "gpt-4o" or type(max_output) is not int or not 1 <= max_output <= self.MAX_OUTPUT:
            raise ValueError("GPT-4o budget requires exact model and output <= 16384")
        return super().reserve(model, max_output)

    def settle(self, request_id, usage):
        prompt, output = getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None)
        if any(type(v) is not int or v < 0 for v in (prompt, output)):
            self.uncertain(request_id)
            raise ValueError("GPT-4o usage is missing/invalid; keep full reservation")
        if prompt > self.MAX_INPUT or output > self.MAX_OUTPUT:
            self.uncertain(request_id)
            raise ValueError("GPT-4o usage exceeds priced context/output limits")
        return super().settle(request_id, usage)
