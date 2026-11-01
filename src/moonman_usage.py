"""Moon Man AI usage + cost telemetry.

Isolated, additive monitoring for Meta Model API spend. Appends one JSON
record per API call to a local JSONL file. This module NEVER raises to its
callers and NEVER changes agent behavior -- all failures are silent.

Data file:  Documents/MoonMan/usage.jsonl  (override: MOONMAN_USAGE_FILE)
Pricing:    Meta Model API, verified 2026-11-01 against
            https://dev.meta.ai/docs/pricing-rate-limits
Tier:       standard (default) or contributor (MOONMAN_PRICE_TIER)
Budgets:    MOONMAN_BUDGET_DAILY_USD / MOONMAN_BUDGET_MONTHLY_USD (display only)
"""

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

PRICING_SOURCE = "https://dev.meta.ai/docs/pricing-rate-limits"
PRICING_VERIFIED = "2026-11-01"

# USD per 1M tokens (Standard tier, muse-spark-1.3). Search queries are USD
# each. Contributor search rate is not tiered on the pricing page, so the
# same $2.50/1k figure is used for both tiers and labeled as assumed.
PRICES = {
    "standard": {
        "input": 1.25,
        "cached_input": 0.15,
        "output": 4.25,
        "search_query": 2.50 / 1000.0,
    },
    "contributor": {
        "input": 0.10,
        "cached_input": 0.002,
        "output": 0.20,
        "search_query": 2.50 / 1000.0,
    },
}

DEFAULT_USAGE_FILE = (
    Path.home() / "Documents" / "MoonMan" / "usage.jsonl"
)


def _tier():
    tier = os.environ.get("MOONMAN_PRICE_TIER", "standard").strip().lower()
    return tier if tier in PRICES else "standard"


def _data_file():
    try:
        return Path(
            os.environ.get("MOONMAN_USAGE_FILE", str(DEFAULT_USAGE_FILE))
        )
    except Exception:
        return DEFAULT_USAGE_FILE


def new_task(prefix="ask"):
    """Mint a task id shared by every API call in one ask / job."""
    try:
        return "%s-%s" % (prefix, uuid.uuid4().hex[:8])
    except Exception:
        return "%s-%d" % (prefix, int(time.time()))


def _num(value, default=0):
    try:
        if value is None or isinstance(value, bool):
            return default
        return int(value)
    except Exception:
        return default


def _usage_tokens(usage):
    """Pull (in, cached, out, reasoning) from chat or responses usage."""
    inp = cached = out = reasoning = 0
    try:
        if usage is None:
            return inp, cached, out, reasoning
        get = (
            usage.get
            if isinstance(usage, dict)
            else lambda k, d=None: getattr(usage, k, d)
        )
        inp = _num(get("prompt_tokens", get("input_tokens", 0)))
        out = _num(get("completion_tokens", get("output_tokens", 0)))
        details = get("prompt_tokens_details", None) or get(
            "input_tokens_details", None
        )
        if details is not None:
            dget = (
                details.get
                if isinstance(details, dict)
                else lambda k, d=None: getattr(details, k, d)
            )
            cached = _num(dget("cached_tokens", 0))
        odetails = get("completion_tokens_details", None) or get(
            "output_tokens_details", None
        )
        if odetails is not None:
            oget = (
                odetails.get
                if isinstance(odetails, dict)
                else lambda k, d=None: getattr(odetails, k, d)
            )
            reasoning = _num(oget("reasoning_tokens", 0))
    except Exception:
        pass
    if cached > inp:
        cached = inp
    return inp, cached, out, reasoning


def _cost(table, inp, cached, out, searches):
    try:
        fresh = max(0, inp - cached)
        return (
            fresh / 1e6 * table["input"]
            + cached / 1e6 * table["cached_input"]
            + out / 1e6 * table["output"]
            + searches * table["search_query"]
        )
    except Exception:
        return 0.0


def record(api, model, usage=None, task_id=None, searches=0,
           prompt_chars=0, completion_chars=0, note=""):
    """Append one usage record. Returns the record dict, or None on failure.

    When the API returns no usage object, tokens are estimated at ~4 chars
    per token from prompt_chars/completion_chars and the record is flagged
    estimated=true. Heard-it-here-first: never billed from estimates.
    """
    try:
        tier = _tier()
        table = PRICES[tier]
        inp, cached, out, reasoning = _usage_tokens(usage)
        estimated = False
        if usage is None and (prompt_chars or completion_chars):
            estimated = True
            inp = int(prompt_chars / 4)
            out = int(completion_chars / 4)
        searches = _num(searches)
        cost = _cost(table, inp, cached, out, searches)
        now = datetime.now(timezone.utc)
        rec = {
            "ts": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "month": now.strftime("%Y-%m"),
            "api": api,
            "model": model,
            "task_id": task_id or "",
            "tier": tier,
            "input_tokens": inp,
            "cached_tokens": cached,
            "output_tokens": out,
            "reasoning_tokens": reasoning,
            "searches": searches,
            "cost_usd": round(cost, 6),
            "estimated": estimated,
            "note": (note or "")[:120],
        }
        path = _data_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(rec) + "\n")
        return rec
    except Exception:
        return None


def _iter_records():
    path = _data_file()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except Exception:
                    continue
    except FileNotFoundError:
        return
    except Exception:
        return


def _env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except Exception:
        return default


def summary():
    """Roll up usage for the Mission Control cost panel. Never raises."""
    out = {
        "tier": _tier(),
        "pricing": PRICES[_tier()],
        "pricing_source": PRICING_SOURCE,
        "pricing_verified": PRICING_VERIFIED,
        "last": None,
        "today_usd": 0.0,
        "today_calls": 0,
        "today_measured": 0,
        "today_estimated": 0,
        "month_usd": 0.0,
        "month_calls": 0,
        "est_month_usd": 0.0,
        "by_task": [],
        "budget_daily_usd": _env_float("MOONMAN_BUDGET_DAILY_USD", 0.0),
        "budget_monthly_usd": _env_float("MOONMAN_BUDGET_MONTHLY_USD", 25.0),
        "budget_note": "Tracking + warnings only. Stops nothing automatically.",
    }
    try:
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        month = now.strftime("%Y-%m")
        tasks = {}
        last = None
        for rec in _iter_records():
            last = rec
            try:
                cost = float(rec.get("cost_usd", 0.0))
            except Exception:
                cost = 0.0
            if rec.get("date") == today:
                out["today_usd"] += cost
                out["today_calls"] += 1
                if rec.get("estimated"):
                    out["today_estimated"] += 1
                else:
                    out["today_measured"] += 1
                task = rec.get("task_id") or "(direct)"
                entry = tasks.get(task, {"cost": 0.0, "calls": 0})
                entry["cost"] += cost
                entry["calls"] += 1
                tasks[task] = entry
            if rec.get("month") == month:
                out["month_usd"] += cost
                out["month_calls"] += 1
        out["last"] = last
        day_of_month = max(1, now.day)
        out["est_month_usd"] = round(
            out["month_usd"] / day_of_month * 30.0, 2
        )
        out["today_usd"] = round(out["today_usd"], 4)
        out["month_usd"] = round(out["month_usd"], 4)
        ranked = sorted(
            tasks.items(), key=lambda kv: kv[1]["cost"], reverse=True
        )[:10]
        out["by_task"] = [
            {
                "task_id": task,
                "cost_usd": round(info["cost"], 4),
                "calls": info["calls"],
            }
            for task, info in ranked
        ]
    except Exception:
        pass
    return out
