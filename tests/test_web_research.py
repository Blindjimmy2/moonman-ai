"""Mocked/offline tests for Moon Man web_research. No network, no API key needed.

Run from the project root:
    python tests/test_web_research.py
"""

import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(__file__.rsplit("tests", 1)[0] + "src"))

import web_research
from web_research import web_research as run_query


def _note(url="https://example.com/ds.pdf", title="Datasheet",
           start=8, end=16, kind="url_citation"):
    note = SimpleNamespace(type=kind, url=url, title=title)
    if start is not None:
        note.start_index = start
    if end is not None:
        note.end_index = end
    return note


def _message(text, notes=()):
    return SimpleNamespace(type="message",
                            content=[SimpleNamespace(text=text, annotations=list(notes))])


def _search_call():
    return SimpleNamespace(type="web_search_call", content=[])


def _fake_client(response=None, error=None, capture=None):
    def _create(**kwargs):
        if capture is not None:
            capture.update(kwargs)
        if error is not None:
            raise error
        return response

    return SimpleNamespace(responses=SimpleNamespace(create=_create))


class QueryValidationTests(unittest.TestCase):
    def test_empty_query_rejected_without_api_call(self):
        with patch.object(web_research, "_client") as factory:
            result = run_query("   ")
        factory.assert_not_called()
        self.assertEqual(result["status"], "error")

    def test_non_string_query_rejected(self):
        with patch.object(web_research, "_client") as factory:
            result = run_query(None)
        factory.assert_not_called()
        self.assertEqual(result["status"], "error")

    def test_long_query_rejected(self):
        with patch.object(web_research, "_client") as factory:
            result = run_query("x" * 501)
        factory.assert_not_called()
        self.assertEqual(result["status"], "error")
        self.assertIn("500", result["error"])


class SearchDetectionTests(unittest.TestCase):
    def test_web_search_call_marks_search_occurred(self):
        response = SimpleNamespace(output=[
            _search_call(),
            _message("Bore is 12.7 mm.", [_note()]),
        ])
        with patch.object(web_research, "_client",
                            return_value=_fake_client(response)):
            result = run_query("shaft collar bore")
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["search_occurred"])

    def test_no_search_call_is_ungrounded(self):
        response = SimpleNamespace(output=[_message("I do not know.")])
        with patch.object(web_research, "_client",
                            return_value=_fake_client(response)):
            result = run_query("obscure part")
        self.assertEqual(result["status"], "ungrounded")
        self.assertFalse(result["search_occurred"])
        self.assertEqual(result["citations"], [])

    def test_citations_without_search_call_still_reported_separately(self):
        response = SimpleNamespace(output=[
            _message("Bore is 12.7 mm.", [_note()]),
        ])
        with patch.object(web_research, "_client",
                            return_value=_fake_client(response)):
            result = run_query("shaft collar bore")
        self.assertFalse(result["search_occurred"])
        self.assertEqual(result["status"], "ungrounded")
        self.assertEqual(len(result["citations"]), 1)
        self.assertEqual(result["citations"][0]["url"],
                         "https://example.com/ds.pdf")


class CitationSpanTests(unittest.TestCase):
    def test_span_links_spec_to_source(self):
        response = SimpleNamespace(output=[
            _search_call(),
            _message("Bore is 12.7 mm.", [_note(start=8, end=16)]),
        ])
        with patch.object(web_research, "_client",
                            return_value=_fake_client(response)):
            result = run_query("bore size")
        cite = result["citations"][0]
        self.assertEqual(cite["start_index"], 8)
        self.assertEqual(cite["end_index"], 16)
        self.assertEqual(cite["cited_text"], "12.7 mm.")

    def test_missing_spans_kept_without_cited_text(self):
        response = SimpleNamespace(output=[
            _search_call(),
            _message("Bore is 12.7 mm.", [_note(start=None, end=None)]),
        ])
        with patch.object(web_research, "_client",
                            return_value=_fake_client(response)):
            result = run_query("bore size")
        cite = result["citations"][0]
        self.assertIsNone(cite["start_index"])
        self.assertIsNone(cite["end_index"])
        self.assertIsNone(cite["cited_text"])

    def test_out_of_range_span_does_not_crash(self):
        response = SimpleNamespace(output=[
            _search_call(),
            _message("short", [_note(start=0, end=999)]),
        ])
        with patch.object(web_research, "_client",
                            return_value=_fake_client(response)):
            result = run_query("bore size")
        self.assertIsNone(result["citations"][0]["cited_text"])

    def test_non_url_annotations_ignored(self):
        response = SimpleNamespace(output=[
            _search_call(),
            _message("text", [_note(kind="other")]),
        ])
        with patch.object(web_research, "_client",
                            return_value=_fake_client(response)):
            result = run_query("bore size")
        self.assertEqual(result["citations"], [])


class RequestShapeTests(unittest.TestCase):
    def test_low_search_context_and_model(self):
        response = SimpleNamespace(output=[_search_call(), _message("done")])
        capture = {}
        with patch.object(web_research, "_client",
                            return_value=_fake_client(response, capture=capture)):
            run_query("MG996R servo dimensions")
        self.assertEqual(capture["model"], "muse-spark-1.3")
        self.assertEqual(capture["tools"],
                         [{"type": "web_search", "search_context_size": "low"}])

    def test_api_error_returns_error_dict(self):
        with patch.object(web_research, "_client",
                            return_value=_fake_client(error=TimeoutError("slow"))):
            result = run_query("anything")
        self.assertEqual(result["status"], "error")
        self.assertIn("slow", result["error"])

    def test_sdk_without_responses_reports_upgrade(self):
        with patch.object(web_research, "_client", return_value=object()):
            result = run_query("anything")
        self.assertEqual(result["status"], "error")
        self.assertIn("responses", result["error"])


class SafetyContractTests(unittest.TestCase):
    def test_results_always_unverified_with_disclaimer(self):
        response = SimpleNamespace(output=[
            _search_call(),
            _message("Bore is 12.7 mm.", [_note()]),
        ])
        with patch.object(web_research, "_client",
                            return_value=_fake_client(response)):
            result = run_query("bore size")
        self.assertFalse(result["verified"])
        self.assertIn("UNVERIFIED", result["disclaimer"])

    def test_missing_key_reports_without_leak(self):
        with patch.object(web_research.os, "getenv", return_value=None):
            result = run_query("anything")
        self.assertEqual(result["status"], "error")
        self.assertIn("META_API_KEY", result["error"])

    def test_result_contains_no_credential_material(self):
        fake_key = "LLM|12345|SECRETKEYMATERIAL"
        response = SimpleNamespace(output=[_search_call(), _message("done")])
        with patch.object(web_research, "_client",
                            return_value=_fake_client(response)):
            with patch.object(web_research.os, "getenv", return_value=fake_key):
                result = run_query("anything")
        self.assertNotIn("SECRETKEYMATERIAL", json.dumps(result))

    def test_long_answer_truncated(self):
        response = SimpleNamespace(output=[
            _search_call(), _message("A" * 9000),
        ])
        with patch.object(web_research, "_client",
                            return_value=_fake_client(response)):
            result = run_query("anything")
        self.assertLessEqual(len(result["answer"]), 4000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
