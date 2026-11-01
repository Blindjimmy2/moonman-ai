"""Tests for project-aware engineering memory. No network, no live API.

DB tests use a temporary database; agent wiring tests patch the DB layer.
Run from the project root:
    python tests/test_project_memory.py
"""

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(__file__.rsplit("tests", 1)[0] + "src"))

import agent
import project_memory
from project_memory import (
    detect_project, get_active_project, latest_checkpoint,
    project_brief, recall_facts, remember_fact, set_active_project,
    write_checkpoint,
)


def _tmp_db(test):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    patcher = patch.object(project_memory, "DB_PATH", Path(tmp.name))
    patcher.start()
    test.addCleanup(patcher.stop)
    test.addCleanup(lambda: Path(tmp.name).unlink(missing_ok=True))


def _save_history(test):
    backup = list(agent.history)
    agent.history.clear()
    test.addCleanup(lambda: (agent.history.clear(), agent.history.extend(backup)))


def _text_response(text):
    message = MagicMock()
    message.tool_calls = []
    message.content = text
    response = MagicMock()
    response.choices = [MagicMock(message=message)]
    return response


def _multi_tool_response(calls):
    items = []
    for index, (name, args) in enumerate(calls):
        call = MagicMock()
        call.id = "call_%d" % index
        call.function.name = name
        call.function.arguments = json.dumps(args)
        items.append(call)
    message = MagicMock()
    message.tool_calls = items
    message.content = "working"
    response = MagicMock()
    response.choices = [MagicMock(message=message)]
    return response


class SchemaTests(unittest.TestCase):
    def test_tables_created_and_projects_seeded(self):
        _tmp_db(self)
        with project_memory.connect() as db:
            tables = {r[0] for r in db.execute(
                "select name from sqlite_master where type = 'table'")}
        self.assertTrue({"projects", "checkpoints", "project_facts", "meta"}
                        <= tables)
        with project_memory.connect() as db:
            names = {r[0] for r in db.execute("select name from projects")}
        self.assertEqual(names, {"moonman", "gumbler", "mac_lite", "general"})

    def test_migration_preserves_memories_table(self):
        _tmp_db(self)
        db = sqlite3.connect(project_memory.DB_PATH)
        db.execute("CREATE TABLE memories (id INTEGER PRIMARY KEY,"
                   " subject TEXT, fact TEXT)")
        db.execute("INSERT INTO memories (subject, fact) VALUES (?, ?)",
                   ("Gumbler", "gear exists"))
        db.commit()
        db.close()
        project_memory.connect().close()
        db = sqlite3.connect(project_memory.DB_PATH)
        rows = db.execute("select subject, fact from memories").fetchall()
        db.close()
        self.assertEqual(rows, [("Gumbler", "gear exists")])


class DetectProjectTests(unittest.TestCase):
    def test_single_project_detected(self):
        self.assertEqual(detect_project("continue the gimbal"), "moonman")
        self.assertEqual(detect_project("resume Gumbler"), "gumbler")
        self.assertEqual(detect_project("mac lite bracket"), "mac_lite")
        self.assertEqual(detect_project("the Gumbling Machine gear"), "gumbler")

    def test_none_or_ambiguous_never_guesses(self):
        self.assertIsNone(detect_project("hello there"))
        self.assertIsNone(detect_project("gumbler vs mac lite"))
        self.assertIsNone(detect_project("continue"))


class FactTests(unittest.TestCase):
    def test_remember_recall_isolated_by_project(self):
        _tmp_db(self)
        remember_fact("gumbler", "drive gear", "module 1 brass", "verified", "calipers")
        remember_fact("moonman", "yoke", "4.5mm thick", "verified", "inspect")
        moon = recall_facts("moonman", "gear yoke thick")
        self.assertEqual(len(moon), 1)
        self.assertEqual(moon[0]["subject"], "yoke")
        gum = recall_facts("gumbler", "gear yoke thick")
        self.assertEqual(len(gum), 1)
        self.assertEqual(gum[0]["subject"], "drive gear")

    def test_invalid_status_and_project_rejected(self):
        _tmp_db(self)
        with self.assertRaises(ValueError):
            remember_fact("moonman", "s", "f", status="maybe")
        with self.assertRaises(ValueError):
            remember_fact("nope", "s", "f")
        with self.assertRaises(ValueError):
            recall_facts("nope", "x")

    def test_overlong_fact_rejected_not_truncated(self):
        _tmp_db(self)
        with self.assertRaises(ValueError):
            remember_fact("moonman", "dims", "x" * 1001)
        self.assertEqual(recall_facts("moonman", ""), [])


class CheckpointTests(unittest.TestCase):
    def test_checkpoint_roundtrip(self):
        _tmp_db(self)
        write_checkpoint("moonman", "round-budget-exhausted", 8, 14,
                         summary="built yokes", verified=["[VERIFIED] yoke"],
                         blockers="horn PCD", next_step="drill yokes")
        row = latest_checkpoint("moonman")
        self.assertEqual(row["turn_status"], "round-budget-exhausted")
        self.assertEqual(row["rounds_used"], 8)
        self.assertEqual(row["tool_calls_used"], 14)
        self.assertEqual(row["next_step"], "drill yokes")
        self.assertIsNone(latest_checkpoint("gumbler"))

    def test_brief_bounded_and_empty_state(self):
        _tmp_db(self)
        self.assertIn("No checkpoints", project_brief("gumbler"))
        write_checkpoint("moonman", "completed", 2, 3, summary="s" * 900,
                         blockers="b", next_step="n")
        brief = project_brief("moonman")
        self.assertLessEqual(len(brief), 750)
        self.assertIn("NEXT: n", brief)
        self.assertIn("Blockers: b", brief)

    def test_active_project_roundtrip(self):
        _tmp_db(self)
        self.assertEqual(get_active_project(), "general")
        set_active_project("gumbler")
        self.assertEqual(get_active_project(), "gumbler")
        with self.assertRaises(ValueError):
            set_active_project("nope")


class ToolHandlerTests(unittest.TestCase):
    def test_handlers_ok_and_fail_closed(self):
        _tmp_db(self)
        ok = project_memory.tool_project_remember(
            "gumbler", "gear", "brass", "verified", "calipers")
        self.assertEqual(ok["status"], "ok")
        found = project_memory.tool_project_recall("gumbler", "gear")
        self.assertEqual(found["count"], 1)
        missing = project_memory.tool_project_checkpoint("gumbler")
        self.assertIsNone(missing["checkpoint"])
        bad = project_memory.tool_project_recall("nope", "x")
        self.assertEqual(bad["status"], "error")


class AgentWiringTests(unittest.TestCase):
    def test_resume_injection_scoped_to_project(self):
        _save_history(self)
        creates = [_text_response("Noted.")]
        with patch.object(agent, "project_brief",
                          return_value="BRIEF-MOONMAN"), \
             patch.object(agent, "set_active_project") as mock_set, \
             patch.object(agent, "get_active_project",
                          return_value="moonman"), \
             patch.object(agent, "recall_facts", return_value=[]), \
             patch.object(agent, "write_checkpoint"), \
             patch.object(agent.client.chat.completions, "create",
                          side_effect=creates) as mock_create:
            agent.ask_moonman("continue the gimbal")
        mock_set.assert_called_once_with("moonman")
        system_text = mock_create.call_args_list[0].kwargs["messages"][0]["content"]
        self.assertIn("Active project: moonman", system_text)
        self.assertIn("BRIEF-MOONMAN", system_text)

    def test_checkpoint_hook_called_per_turn(self):
        _save_history(self)
        call = ("web_research", {"query": "x"})
        creates = [_multi_tool_response([call]), _text_response("Done.")]
        canned = {"status": "ok", "query": "x", "answer": "a",
                  "citations": [], "search_occurred": True,
                  "verified": False, "disclaimer": "d"}
        with patch.object(agent, "set_active_project"), \
             patch.object(agent, "get_active_project",
                          return_value="moonman"), \
             patch.object(agent, "recall_facts", return_value=[]), \
             patch.object(agent, "project_brief", return_value="b"), \
             patch.object(agent, "write_checkpoint") as mock_write, \
             patch.object(agent, "web_research", return_value=dict(canned)), \
             patch.object(agent.client.chat.completions, "create",
                          side_effect=creates):
            agent.ask_moonman("research horns")
        mock_write.assert_called_once()
        kwargs = mock_write.call_args.kwargs
        self.assertEqual(kwargs["project"], "moonman")
        self.assertEqual(kwargs["turn_status"], "completed")

    def test_hook_failure_does_not_break_turn(self):
        _save_history(self)
        creates = [_text_response("Still here.")]
        with patch.object(agent, "set_active_project"), \
             patch.object(agent, "get_active_project",
                          return_value="moonman"), \
             patch.object(agent, "recall_facts", return_value=[]), \
             patch.object(agent, "project_brief", return_value="b"), \
             patch.object(agent, "write_checkpoint",
                          side_effect=RuntimeError("disk down")), \
             patch.object(agent.client.chat.completions, "create",
                          side_effect=creates):
            answer = agent.ask_moonman("status check")
        self.assertEqual(answer, "Still here.")

    def test_tool_cap_status_distinguished(self):
        _save_history(self)
        call = ("web_research", {"query": "x"})
        creates = [_multi_tool_response([call] * 3) for _ in range(7)]
        canned = {"status": "ok", "query": "x", "answer": "a",
                  "citations": [], "search_occurred": True,
                  "verified": False, "disclaimer": "d"}
        with patch.object(agent, "set_active_project"), \
             patch.object(agent, "get_active_project",
                          return_value="moonman"), \
             patch.object(agent, "recall_facts", return_value=[]), \
             patch.object(agent, "project_brief", return_value="b"), \
             patch.object(agent, "write_checkpoint"), \
             patch.object(agent, "web_research", return_value=dict(canned)), \
             patch.object(agent.client.chat.completions, "create",
                          side_effect=creates):
            answer = agent.ask_moonman("research everything")
        self.assertIn("too many tool calls", answer)
        self.assertIn("tool-cap-exhausted", agent.history[-1]["content"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
