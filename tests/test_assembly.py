"""Tests for Track 2 assembly tools + coexistence safety. Mocked only.

Covers: component registry allow/deny, ownership claim commands, new tool
registration + dispatch, doc-pinning halt, stale-bridge hint.
Run from the project root:
    python tests/test_assembly.py
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(__file__.rsplit("tests", 1)[0] + "src"))

import agent

NEW_TOOLS = {
    "fusion_save_document": "save_document",
    "fusion_delete_body": "delete_body",
    "fusion_delete_feature": "delete_feature",
    "fusion_delete_sketch": "delete_sketch",
    "fusion_document_info": "document_info",
    "fusion_check_clearance": "check_clearance",
    "fusion_interference_check": "interference_check",
    "fusion_align_bodies": "align_bodies",
}


def _tmp_registry(test):
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.close()
    Path(tmp.name).write_text('{"owned": []}', encoding="utf-8")
    patcher = patch.object(agent, "COMPONENT_REGISTRY", Path(tmp.name))
    patcher.start()
    test.addCleanup(patcher.stop)
    test.addCleanup(lambda: Path(tmp.name).unlink(missing_ok=True))


def _isolate_db(test):
    patchers = [
        patch.object(agent, "set_active_project"),
        patch.object(agent, "get_active_project", return_value="general"),
        patch.object(agent, "recall_facts", return_value=[]),
        patch.object(agent, "project_brief", return_value="b"),
        patch.object(agent, "write_checkpoint"),
    ]
    for patcher in patchers:
        patcher.start()
    test.addCleanup(lambda: [p.stop() for p in patchers])


def _save_history(test):
    backup = list(agent.history)
    agent.history.clear()
    test.addCleanup(lambda: (agent.history.clear(), agent.history.extend(backup)))


def _tool_response(name, args):
    call = MagicMock()
    call.id = "call_1"
    call.function.name = name
    call.function.arguments = json.dumps(args)
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


class RegistryTests(unittest.TestCase):
    def test_register_and_load_roundtrip(self):
        _tmp_registry(self)
        agent._register_owned("BRACKET")
        self.assertIn("BRACKET", agent._load_owned())

    def test_check_denies_unowned_write(self):
        _tmp_registry(self)
        denial = agent._check_owned("move_body", {"component": "NOPE"})
        self.assertIsNotNone(denial)
        self.assertEqual(denial["status"], "error")
        self.assertIn("moonman owns NOPE", denial["error"])

    def test_check_allows_owned_and_reads(self):
        _tmp_registry(self)
        agent._register_owned("MINE")
        self.assertIsNone(
            agent._check_owned("move_body", {"component": "MINE"}))
        self.assertIsNone(
            agent._check_owned("inspect_design", {"component": "ANY"}))
        self.assertIsNone(
            agent._check_owned("create_box", {}))

    def test_fusion_command_denies_without_network(self):
        _tmp_registry(self)
        with patch.object(agent._moonman_http, "urlopen") as mock_open:
            result = agent.moonman_fusion_command(
                "delete_body", {"component": "NOPE"})
        mock_open.assert_not_called()
        self.assertEqual(result["status"], "error")


class ClaimCommandTests(unittest.TestCase):
    def test_own_and_release(self):
        _tmp_registry(self)
        self.assertIn("now owns",
                      agent.ask_moonman("moonman owns BRACKET"))
        self.assertIn("BRACKET", agent._load_owned())
        self.assertIn("released",
                      agent.ask_moonman("moonman release BRACKET"))
        self.assertNotIn("BRACKET", agent._load_owned())
        self.assertIn("not Moon Man-owned",
                      agent.ask_moonman("moonman release BRACKET"))


class ToolRegistrationTests(unittest.TestCase):
    def test_new_tools_registered(self):
        names = {t["function"]["name"] for t in agent.CAD_TOOLS}
        for tool in NEW_TOOLS:
            self.assertIn(tool, names)

    def test_hole_plane_param_present(self):
        for tool in agent.CAD_TOOLS:
            if tool["function"]["name"] == "fusion_create_hole":
                props = tool["function"]["parameters"]["properties"]
                self.assertIn("plane", props)
                return
        self.fail("fusion_create_hole missing")

    def test_hole_plane_verified_wording(self):
        for tool in agent.CAD_TOOLS:
            if tool["function"]["name"] == "fusion_create_hole":
                desc = tool["function"]["parameters"]["properties"][
                    "plane"].get("description", "")
                for keyword in ("volume_change_mm3", "MISS", "symmetric",
                                "world", "one-sided"):
                    self.assertIn(keyword, desc)
                return
        self.fail("fusion_create_hole missing")


class DispatchTests(unittest.TestCase):
    def test_new_tools_dispatch_to_bridge_actions(self):
        _save_history(self)
        _isolate_db(self)
        for tool, action in NEW_TOOLS.items():
            args = {"component": "MINE"}
            creates = [_tool_response(tool, args), _text_response("ok")]
            with patch.object(
                    agent.client.chat.completions, "create",
                    side_effect=creates), \
                 patch.object(agent, "moonman_fusion_command",
                              return_value={"status": "success",
                                            "result": {}}) as mock_fusion:
                agent.ask_moonman("do fusion work")
            mock_fusion.assert_called_once_with(action, args)


class PinningTests(unittest.TestCase):
    def test_doc_change_halts_turn(self):
        _save_history(self)
        _isolate_db(self)
        args = {"component": "MINE"}
        creates = [_tool_response("fusion_document_info", args),
                   _tool_response("fusion_document_info", args)]
        results = [{"status": "success", "document": "DocA", "result": {}},
                   {"status": "success", "document": "DocB", "result": {}}]
        with patch.object(agent.client.chat.completions, "create",
                          side_effect=creates), \
             patch.object(agent, "moonman_fusion_command",
                          side_effect=results):
            answer = agent.ask_moonman("inspect things")
        self.assertIn("changed mid-turn", answer)
        self.assertIn("error-halt", agent.history[-1]["content"])

    def test_missing_document_key_old_bridge_compatible(self):
        _save_history(self)
        _isolate_db(self)
        args = {"component": "MINE"}
        creates = [_tool_response("fusion_document_info", args),
                   _text_response("fine")]
        with patch.object(agent.client.chat.completions, "create",
                          side_effect=creates), \
             patch.object(agent, "moonman_fusion_command",
                          return_value={"status": "success", "result": {}}):
            answer = agent.ask_moonman("inspect things")
        self.assertEqual(answer, "fine")

    def test_stale_bridge_hint(self):
        _save_history(self)
        _isolate_db(self)
        args = {"width_mm": 10, "depth_mm": 10, "height_mm": 10}
        creates = [_tool_response("fusion_create_box", args)]
        error = {"status": "error",
                 "error": "HTTP Error 400: Unsupported action"}
        with patch.object(agent.client.chat.completions, "create",
                          side_effect=creates), \
             patch.object(agent, "moonman_fusion_command", return_value=error):
            answer = agent.ask_moonman("make a box")
        self.assertIn("Restart the MoonManBridge", answer)


if __name__ == "__main__":
    unittest.main(verbosity=2)
