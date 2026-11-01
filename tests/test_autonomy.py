"""Tests for Moon Man engineering autonomy (O1-O3). No network, no Fusion needed.

Covers: turn-outcome records persisted to history, VERIFIED/FAILED/UNVERIFIED
labeling, scratchpad loading bounds, round-budget NEXT capture and fallback.

Run from the project root:
    python tests/test_autonomy.py
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(__file__.rsplit("tests", 1)[0] + "src"))

import agent
import engineering_tools


def _save_history(test):
    test._history_backup = list(agent.history)
    agent.history.clear()
    test.addCleanup(lambda: (agent.history.clear(),
                              agent.history.extend(test._history_backup)))


def _tool_response(name="web_research", args=None):
    call = MagicMock()
    call.id = "call_1"
    call.function.name = name
    call.function.arguments = json.dumps(args or {"query": "servo dims"})
    message = MagicMock()
    message.tool_calls = [call]
    message.content = "working"
    response = MagicMock()
    response.choices = [MagicMock(message=message)]
    return response


def _text_response(text):
    message = MagicMock()
    message.tool_calls = []
    message.content = text
    response = MagicMock()
    response.choices = [MagicMock(message=message)]
    return response


def _raw_tool_response(name, raw_arguments):
    call = MagicMock()
    call.id = "call_1"
    call.function.name = name
    call.function.arguments = raw_arguments
    message = MagicMock()
    message.tool_calls = [call]
    message.content = "working"
    response = MagicMock()
    response.choices = [MagicMock(message=message)]
    return response


CANNED_RESEARCH = {
    "status": "ok",
    "query": "servo dims",
    "answer": "Bore 12.7mm per datasheet listing.",
    "citations": [{"url": "https://example.com/ds", "title": "DS",
                   "start_index": 0, "end_index": 4, "cited_text": "Bore"}],
    "search_occurred": True,
    "verified": False,
    "disclaimer": "UNVERIFIED",
}


class OutcomeFormatTests(unittest.TestCase):
    def test_verified_and_failed_labels(self):
        log = [
            ("fusion_create_box",
             {"width_mm": 10, "depth_mm": 5, "height_mm": 3},
             {"status": "ok", "component": "bracket"}),
            ("fusion_inspect_design", {},
             {"status": "error", "error": "bridge busy"}),
        ]
        outcome = agent.build_outcome(log, "error-halt")
        self.assertIn("TURN OUTCOME", outcome)
        self.assertIn("[VERIFIED]", outcome)
        self.assertIn("[FAILED]", outcome)
        self.assertIn("fusion_create_box", outcome)
        self.assertIn("10", outcome)  # dimensions preserved from args
        self.assertIn("bridge busy", outcome)
        self.assertIn("error-halt", outcome)

    def test_web_research_marked_unverified(self):
        outcome = agent.build_outcome(
            [("web_research", {"query": "bore"}, CANNED_RESEARCH)],
            "completed")
        self.assertIn("[UNVERIFIED]", outcome)
        self.assertIn("search_occurred=True", outcome)
        self.assertIn("citations=1", outcome)

    def test_outcome_is_bounded(self):
        log = [(f"fusion_create_box", {"n": i},
                {"status": "ok", "index": i}) for i in range(25)]
        outcome = agent.build_outcome(log, "completed")
        self.assertLessEqual(len(outcome), 1600)
        self.assertIn("more", outcome)

    def test_empty_log_reports_no_tools(self):
        outcome = agent.build_outcome([], "completed")
        self.assertIn("no tool calls", outcome)


class ScratchpadTests(unittest.TestCase):
    def test_missing_scratchpad_reports_none(self):
        with patch.object(agent, "OBJECTIVE_FILE",
                          Path("does_not_exist_12345.md")):
            self.assertIn("None recorded", agent.read_objective())

    def test_long_scratchpad_truncated(self):
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".md", delete=False,
                encoding="utf-8") as handle:
            handle.write("# Objective\n" + "x" * 5000)
            path = handle.name
        try:
            with patch.object(agent, "OBJECTIVE_FILE", Path(path)):
                text = agent.read_objective()
            self.assertLessEqual(len(text), 2100)
            self.assertIn("truncated", text)
        finally:
            Path(path).unlink()

    def test_unreadable_scratchpad_never_raises(self):
        with patch.object(agent, "OBJECTIVE_FILE", Path("\x00")):
            text = agent.read_objective()
        self.assertIn("None recorded", text)


class TurnWiringTests(unittest.TestCase):
    def setUp(self):
        self._patches = [
            patch.object(agent, "set_active_project"),
            patch.object(agent, "get_active_project", return_value="general"),
            patch.object(agent, "recall_facts", return_value=[]),
            patch.object(agent, "project_brief", return_value="test-brief"),
            patch.object(agent, "write_checkpoint"),
        ]
        for patcher in self._patches:
            patcher.start()
        self.addCleanup(lambda: [p.stop() for p in self._patches])
    def test_outcome_persisted_to_history(self):
        _save_history(self)
        creates = [_tool_response(), _text_response("Research noted.")]
        with patch.object(agent.client.chat.completions, "create",
                          side_effect=creates):
            with patch.object(agent, "web_research",
                              return_value=dict(CANNED_RESEARCH)):
                answer = agent.ask_moonman("Research servo horn dimensions")
        self.assertEqual(answer, "Research noted.")
        stored = agent.history[-1]["content"]
        self.assertIn("TURN OUTCOME", stored)
        self.assertIn("web_research", stored)
        self.assertIn("search_occurred=True", stored)

    def test_round_exhaustion_captures_next(self):
        _save_history(self)
        summary = ("PROGRESS: researched servo dims.\n"
                   "NEXT: call fusion_create_box for bracket base.\n"
                   "BLOCKED: none")
        creates = [_tool_response() for _ in range(8)] + [_text_response(summary)]
        with patch.object(agent.client.chat.completions, "create",
                          side_effect=creates) as mock_create:
            with patch.object(agent, "web_research",
                              return_value=dict(CANNED_RESEARCH)):
                answer = agent.ask_moonman("Design a servo bracket set")
        self.assertIn("NEXT:", answer)
        self.assertIn("fusion_create_box", answer)
        last_kwargs = mock_create.call_args_list[-1].kwargs
        self.assertEqual(last_kwargs.get("tool_choice"), "none")
        stored = agent.history[-1]["content"]
        self.assertIn("round-budget-exhausted", stored)

    def test_summary_failure_falls_back_to_fixed_text(self):
        _save_history(self)
        creates = [_tool_response() for _ in range(8)] + [RuntimeError("down")]
        with patch.object(agent.client.chat.completions, "create",
                          side_effect=creates):
            with patch.object(agent, "web_research",
                              return_value=dict(CANNED_RESEARCH)):
                answer = agent.ask_moonman("Design a servo bracket set")
        self.assertIn("eight-round safety limit", answer)


class ReadErrorRecoveryTests(unittest.TestCase):
    def setUp(self):
        self._patches = [
            patch.object(agent, "set_active_project"),
            patch.object(agent, "get_active_project", return_value="general"),
            patch.object(agent, "recall_facts", return_value=[]),
            patch.object(agent, "project_brief", return_value="test-brief"),
            patch.object(agent, "write_checkpoint"),
        ]
        for patcher in self._patches:
            patcher.start()
        self.addCleanup(lambda: [p.stop() for p in self._patches])
    def test_read_error_continues_turn(self):
        _save_history(self)
        creates = [
            _tool_response("engineering_list",
                           {"path": "moonman_engineering/active_objective.md"}),
            _text_response("Path corrected, moving on."),
        ]
        with patch.object(agent.client.chat.completions, "create",
                          side_effect=creates):
            answer = agent.ask_moonman("Review the saved engineering objective")
        self.assertEqual(answer, "Path corrected, moving on.")
        stored = agent.history[-1]["content"]
        self.assertIn("[FAILED]", stored)
        self.assertIn("engineering_list", stored)
        self.assertIn("Status: completed", stored)

    def test_write_error_still_halts(self):
        _save_history(self)
        creates = [_tool_response(
            "fusion_create_box",
            {"width_mm": 10, "depth_mm": 5, "height_mm": 3})]
        with patch.object(agent.client.chat.completions, "create",
                          side_effect=creates):
            with patch.object(
                    agent, "moonman_fusion_command",
                    return_value={"status": "error", "error": "bridge down"}):
                answer = agent.ask_moonman("Create a bracket base")
        self.assertIn("Stopped without requesting further actions", answer)
        self.assertIn("error-halt", agent.history[-1]["content"])


class ToolLoopRobustnessTests(unittest.TestCase):
    def setUp(self):
        self._patches = [
            patch.object(agent, "set_active_project"),
            patch.object(agent, "get_active_project", return_value="general"),
            patch.object(agent, "recall_facts", return_value=[]),
            patch.object(agent, "project_brief", return_value="test-brief"),
            patch.object(agent, "write_checkpoint"),
        ]
        for patcher in self._patches:
            patcher.start()
        self.addCleanup(lambda: [p.stop() for p in self._patches])

    def test_malformed_tool_arguments_halt_gracefully(self):
        _save_history(self)
        creates = [_raw_tool_response("fusion_create_box", "{not json")]
        with patch.object(agent.client.chat.completions, "create",
                          side_effect=creates):
            answer = agent.ask_moonman("Make a bracket base")
        self.assertIn("fusion_create_box failed", answer)
        self.assertIn("Stopped without requesting further actions", answer)
        self.assertIn("error-halt", agent.history[-1]["content"])

    def test_track2_read_tools_are_retryable(self):
        for tool in ("fusion_document_info", "fusion_check_clearance",
                     "fusion_interference_check"):
            self.assertIn(tool, agent.RETRYABLE_READ_TOOLS)

    def test_failed_clearance_check_continues_turn(self):
        _save_history(self)
        creates = [
            _tool_response("fusion_check_clearance",
                           {"component_a": "a", "component_b": "b"}),
            _text_response("Noted, will inspect instead."),
        ]
        with patch.object(agent.client.chat.completions, "create",
                          side_effect=creates):
            with patch.object(
                    agent, "moonman_fusion_command",
                    return_value={"status": "error", "error": "bridge down"}):
                answer = agent.ask_moonman("Check clearance between bodies")
        self.assertEqual(answer, "Noted, will inspect instead.")
        stored = agent.history[-1]["content"]
        self.assertIn("[FAILED]", stored)
        self.assertIn("fusion_check_clearance", stored)
        self.assertIn("Status: completed", stored)


class DirectivePathTests(unittest.TestCase):
    def test_directive_uses_workspace_relative_scratchpad_path(self):
        self.assertIn("objectives/", agent.AUTONOMY_DIRECTIVE)
        self.assertNotIn("moonman_engineering/active_objective.md",
                         agent.AUTONOMY_DIRECTIVE)

    def test_directive_covers_failed_checks(self):
        self.assertIn("never build dependent geometry on assumed state",
                      agent.AUTONOMY_DIRECTIVE)


class EngineeringListHintTests(unittest.TestCase):
    def test_missing_path_error_guides_to_workspace_paths(self):
        with self.assertRaises(ValueError) as ctx:
            engineering_tools.engineering_list(
                "moonman_engineering/active_objective.md")
        self.assertIn("workspace-relative", str(ctx.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
