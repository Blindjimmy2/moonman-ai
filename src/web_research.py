"""Meta-native Search Grounding for Moon Man (read-only engineering research).

Uses the Meta Model API Responses API with the built-in web_search tool.
No new credentials, no new dependencies. Never starts prints, never
modifies CAD, never touches hardware. Never acts on returned dimensions.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

MODEL = "muse-spark-1.3"
TIMEOUT = 45.0
MAX_QUERY_CHARS = 500
MAX_ANSWER_CHARS = 4000
SEARCH_CONTEXT_SIZE = "low"

DISCLAIMER = (
    "Research candidates only -- dimensions and specs below are UNVERIFIED. "
    "Confirm against the cited manufacturer source before use in CAD or prints."
)

SYSTEM = (
    "You are Moon Man's engineering research assistant. Answer ONLY from live "
    "web search results. Scope: manufacturer datasheets, servo dimensions, "
    "shaft specifications, mounting-hole spacing, component identification. "
    "Cite every factual claim with its source. If search returns nothing "
    "relevant, say so. Never present a dimension as a confirmed specification."
)


def _client():
    key = os.getenv("META_API_KEY")
    if not key:
        raise RuntimeError("META_API_KEY missing from .env")
    return OpenAI(base_url="https://api.meta.ai/v1", api_key=key, timeout=TIMEOUT)


def _citation(note):
    url = getattr(note, "url", "") or ""
    title = getattr(note, "title", "") or ""

    def _index(value):
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    return {
        "url": url,
        "title": title,
        "start_index": _index(getattr(note, "start_index", None)),
        "end_index": _index(getattr(note, "end_index", None)),
        "cited_text": None,
    }


def _parse(query, response):
    answer_parts = []
    citations = []
    saw_search_call = False

    try:
        output = getattr(response, "output", None) or []
        for item in output:
            if getattr(item, "type", "") == "web_search_call":
                saw_search_call = True
            for content in getattr(item, "content", None) or []:
                text = getattr(content, "text", "")
                if text:
                    answer_parts.append(text)
                for note in getattr(content, "annotations", None) or []:
                    if getattr(note, "type", "") == "url_citation":
                        cite = _citation(note)
                        if cite["url"]:
                            citations.append(cite)
    except Exception as error:
        return {"status": "error", "error": "Parse failed: " + str(error)[:300]}

    answer = "\n".join(answer_parts).strip()[:MAX_ANSWER_CHARS]

    seen = set()
    unique = []
    for cite in citations:
        key = (cite["url"], cite["start_index"], cite["end_index"])
        if key in seen:
            continue
        seen.add(key)
        start = cite["start_index"]
        end = cite["end_index"]
        if (
            isinstance(start, int)
            and isinstance(end, int)
            and 0 <= start < end <= len(answer)
        ):
            cite["cited_text"] = answer[start:end]
        unique.append(cite)

    return {
        "status": "ok" if saw_search_call else "ungrounded",
        "query": query,
        "answer": answer or "No grounded answer returned.",
        "citations": unique,
        "search_occurred": saw_search_call,
        "verified": False,
        "disclaimer": DISCLAIMER,
    }


def web_research(query):
    """Run one bounded, read-only web research query. Returns a dict."""
    if not isinstance(query, str) or not query.strip():
        return {"status": "error", "error": "Query required."}
    query = " ".join(query.split())
    if len(query) > MAX_QUERY_CHARS:
        return {"status": "error", "error": "Query too long (max 500 chars)."}

    try:
        client = _client()
        if not hasattr(client, "responses"):
            return {
                "status": "error",
                "error": "SDK lacks client.responses; upgrade openai package.",
            }
        response = client.responses.create(
            model=MODEL,
            input=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": query},
            ],
            tools=[{"type": "web_search", "search_context_size": SEARCH_CONTEXT_SIZE}],
        )
    except Exception as error:
        return {"status": "error", "error": str(error)[:500]}

    return _parse(query, response)


if __name__ == "__main__":
    import json
    import sys

    print(
        json.dumps(
            web_research(
                " ".join(sys.argv[1:]) or "MG996R servo dimensions datasheet"
            ),
            indent=2,
        )
    )
