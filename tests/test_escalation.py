"""Tests for research-before-escalation policy + objective runner. Mocked only.

Covers: RUN footer parsing, structured escalation records, evidence
validation (checked vs merely suggested), bounce-once behavior, runner
stop/continue/cap logic, print-confirm guard, directive wording.
Run from the project root:
    python tests/test_escalation.py
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(__file__.rsplit("tests", 1)[0] + "src"))

import agent
import objective_runner as runner
import project_memory
from project_memory import remember_fact, facts_since

GOOD_RECORD = """RUN: needs_human
ESCALATION:
question: what is the horn PCD?
kind: ordinary
checked:
- memory: horn PCD -> no facts found
- web: MG995 horn PCD -> 2 citations, unverified 14mm claim
- geometry: inspect yokes -> no horn present
conflicts: web says 14mm, nothing confirmed
confidence: low
why_human: need measured PCD before drilling pivots
"""

TWO_CAT_EVIDENCE = [
    "[VERIFIED] project_recall: facts=[]",
    "[UNVERIFIED] web_research: search_occurred=True, citations=2 (research only)",
]


def _row(status="completed", rounds=2, calls=3, verified=(), cid=7,
         blockers=""):
    import json
    return {"id": cid, "project": "moonman", "turn_status": status,
            "rounds_used": rounds, "tool_calls_used": calls,
            "verified_json": json.dumps(list(verified)),
            "blockers": blockers, "next_step": ""}


class FooterParserTests(unittest.TestCase):
    def test_dispositions_parse(self):
        for text, want in [("RUN: done", "done"),
                           ("run: continue", "continue"),
                           ("RUN: needs_human", "needs_human"),
                           ("Done.\nRUN: done - all built", "done")]:
            self.assertEqual(runner.parse_footer(text)["disposition"],
                             want, text)

    def test_missing_footer_is_unknown(self):
        parsed = runner.parse_footer("All done, no footer here.")
        self.assertEqual(parsed["disposition"], "unknown")

    def test_last_footer_wins(self):
        parsed = runner.parse_footer("RUN: continue\nmore work\nRUN: done")
        self.assertEqual(parsed["disposition"], "done")


class EscalationRecordTests(unittest.TestCase):
    def test_valid_record_parses(self):
        parsed = runner.parse_escalation(GOOD_RECORD)
        self.assertTrue(parsed["ok"], parsed.get("errors"))
        record = parsed["record"]
        self.assertEqual(record["question"], "what is the horn PCD?")
        self.assertEqual(record["kind"], "ordinary")
        self.assertEqual(record["confidence"], "low")
        self.assertIn("memory", record["checked"])
        self.assertIn("web", record["checked"])
        self.assertIn("geometry", record["checked"])

    def test_missing_fields_rejected(self):
        parsed = runner.parse_escalation("RUN: needs_human\nESCALATION:\n"
                                         "question: x?\n")
        self.assertFalse(parsed["ok"])
        self.assertTrue(parsed["errors"])

    def test_missing_block_rejected(self):
        parsed = runner.parse_escalation("RUN: needs_human\nno record\n")
        self.assertFalse(parsed["ok"])

    def test_immediate_kinds_need_no_evidence(self):
        for kind in ("safety", "authorization", "irreversible",
                     "design_intent"):
            record = {"question": "q", "kind": kind, "checked": {},
                      "conflicts": "", "confidence": "high",
                      "why_human": "w"}
            result = runner.validate_escalation(record, set())
            self.assertTrue(result["valid"], (kind, result))

    def test_ordinary_needs_two_evidenced_categories(self):
        parsed = runner.parse_escalation(GOOD_RECORD)
        record = parsed["record"]
        evidenced = runner.evidence_categories(
            [_row(verified=TWO_CAT_EVIDENCE)])
        self.assertEqual(evidenced, {"memory", "web"})
        result = runner.validate_escalation(record, evidenced)
        self.assertTrue(result["valid"], result)

    def test_single_category_bounced(self):
        parsed = runner.parse_escalation(GOOD_RECORD)
        result = runner.validate_escalation(parsed["record"], {"memory"})
        self.assertFalse(result["valid"])
        self.assertTrue(result["reasons"])

    def test_suggested_source_does_not_count(self):
        text = GOOD_RECORD.replace(
            "- geometry: inspect yokes -> no horn present",
            "- geometry: inspect yokes -> ")
        parsed = runner.parse_escalation(text)
        record = parsed["record"]
        self.assertNotIn("geometry", record["checked"])
        result = runner.validate_escalation(
            record, {"memory", "web", "geometry"})
        self.assertTrue(result["valid"], result)

    def test_negative_result_counts_as_checked(self):
        parsed = runner.parse_escalation(GOOD_RECORD)
        record = parsed["record"]
        self.assertEqual(record["checked"]["memory"][0][1],
                         "no facts found")
        result = runner.validate_escalation(record, {"memory", "web"})
        self.assertTrue(result["valid"], result)

    def test_unknown_kind_rejected(self):
        parsed = runner.parse_escalation(
            GOOD_RECORD.replace("kind: ordinary", "kind: whenever"))
        self.assertFalse(parsed["ok"])


class EvidenceTests(unittest.TestCase):
    def test_tool_to_category_mapping(self):
        rows = [_row(verified=[
            "[VERIFIED] project_recall: facts=[]",
            "[VERIFIED] engineering_read: saved=x",
            "[UNVERIFIED] web_research: search_occurred=True, citations=1 (research only)",
            "[UNVERIFIED] web_research: search_occurred=False, citations=0 (research only)",
            "[VERIFIED] fusion_inspect_geometry: args={} vol=1",
            "[VERIFIED] fusion_check_clearance: args={} gap=5",
            "[VERIFIED] fusion_interference_check: args={} hit=False",
            "[VERIFIED] fusion_create_box: args={} ok",
            "[FAILED] project_recall: disk down",
        ])]
        self.assertEqual(runner.evidence_categories(rows),
                         {"memory", "web", "geometry"})

    def test_failed_and_build_tools_excluded(self):
        rows = [_row(verified=[
            "[FAILED] fusion_inspect_geometry: bridge down",
            "[VERIFIED] fusion_create_box: args={} ok",
        ])]
        self.assertEqual(runner.evidence_categories(rows), set())


class RunnerTests(unittest.TestCase):
    def _run(self, replies, rows, **kwargs):
        prompts = []
        script = list(replies)
        crow = list(rows)

        def turn_fn(prompt):
            prompts.append(prompt)
            return script.pop(0)

        def read_checkpoint(project):
            self.assertEqual(project, "moonman")
            return crow.pop(0)

        options = {"turn_fn": turn_fn,
                   "read_checkpoint": read_checkpoint,
                   "set_active": lambda name: name,
                   "assumptions_fn": lambda project, since: []}
        options.update(kwargs)
        report = runner.run_objective("build the test cube", "moonman",
                                      **options)
        return report, prompts

    def test_done_stops_after_one_turn(self):
        report, prompts = self._run(["Cube built.\nRUN: done"],
                                    [_row()])
        self.assertEqual(report["status"], "done")
        self.assertEqual(report["turns"], 1)
        self.assertEqual(len(prompts), 1)

    def test_continue_loops_then_caps(self):
        report, _ = self._run(["working\nRUN: continue"] * 5,
                              [_row(cid=i) for i in range(5)],
                              max_turns=3)
        self.assertEqual(report["status"], "run_cap")
        self.assertEqual(report["turns"], 3)

    def test_budget_exhausted_without_footer_resumes(self):
        report, _ = self._run(["working, no footer",
                               "finished\nRUN: done"],
                              [_row(status="round-budget-exhausted"),
                               _row(cid=8)])
        self.assertEqual(report["status"], "done")
        self.assertEqual(report["turns"], 2)

    def test_completed_without_footer_is_needs_human(self):
        report, _ = self._run(["stopped talking\n"], [_row()])
        self.assertEqual(report["status"], "needs_human")
        self.assertIn("footer", report["reply_tail"].lower()
                      + str(report["validation_warnings"]).lower())

    def test_valid_escalation_accepted(self):
        report, _ = self._run([GOOD_RECORD],
                              [_row(verified=TWO_CAT_EVIDENCE)])
        self.assertEqual(report["status"], "needs_human")
        self.assertEqual(report["escalation"]["question"],
                         "what is the horn PCD?")
        self.assertEqual(report["turns"], 1)

    def test_invalid_ordinary_bounced_once_then_accepted(self):
        bad = GOOD_RECORD
        report, prompts = self._run([bad, bad],
                                    [_row(verified=[
                                        "[VERIFIED] project_recall: facts=[]",
                                    ]), _row(cid=8, verified=[
                                        "[VERIFIED] project_recall: facts=[]",
                                    ])])
        self.assertEqual(report["status"], "needs_human")
        self.assertEqual(report["turns"], 2)
        self.assertIn("ESCALATION-REJECTED", prompts[1])
        self.assertTrue(report["validation_warnings"])

    def test_safety_accepted_immediately(self):
        text = ("RUN: needs_human\nESCALATION:\nquestion: hot?\n"
                "kind: safety\nchecked:\nconflicts: none\n"
                "confidence: high\nwhy_human: heater fault\n")
        report, _ = self._run([text], [_row(verified=[])])
        self.assertEqual(report["status"], "needs_human")
        self.assertEqual(report["turns"], 1)

    def test_transient_error_retried_once(self):
        report, _ = self._run(["x\nRUN: continue", "ok\nRUN: done"],
                              [_row(status="error-halt",
                                      blockers="[FAILED] fusion_x: bridge down"),
                               _row(cid=8)])
        self.assertEqual(report["status"], "done")
        self.assertEqual(report["turns"], 2)

    def test_persistent_error_escalates(self):
        report, _ = self._run(["x", "y"],
                              [_row(status="error-halt",
                                      blockers="[FAILED] fusion_x: bridge down"),
                               _row(cid=8, status="error-halt",
                                      blockers="[FAILED] fusion_x: bridge down")])
        self.assertEqual(report["status"], "needs_human")
        self.assertEqual(report["turns"], 2)

    def test_non_transient_error_escalates_immediately(self):
        report, _ = self._run(["x"], [_row(status="error-halt",
                                           blockers="[FAILED] fusion_create_box: bad args")])
        self.assertEqual(report["status"], "needs_human")
        self.assertEqual(report["turns"], 1)

    def test_outbound_prompts_never_confirm_prints(self):
        confirms = ("confirm print", "yes print", "yes print it",
                    "yes, print it", "print it")
        report, prompts = self._run([GOOD_RECORD, GOOD_RECORD],
                                    [_row(verified=[]), _row(cid=8,
                                                             verified=[])])
        self.assertEqual(report["status"], "needs_human")
        for prompt in prompts:
            self.assertNotIn(prompt.strip().lower(), confirms)
            self.assertNotIn("confirm print", prompt.lower())

    def test_invalid_project_rejected(self):
        with self.assertRaises(ValueError):
            runner.run_objective("x", "general")
        with self.assertRaises(ValueError):
            runner.run_objective("x", "nope")

    def test_assumptions_collected(self):
        rows = [{"subject": "s", "fact": "f", "status": "assumption",
                 "provenance": "p", "updated_at": "t"}]
        report, _ = self._run(["ok\nRUN: done"], [_row()],
                              assumptions_fn=lambda p, s: list(rows))
        self.assertEqual(report["assumptions"], rows)


class DirectiveTests(unittest.TestCase):
    def test_ladder_and_footer_in_directive(self):
        text = agent.AUTONOMY_DIRECTIVE
        for keyword in ("R1", "R2", "R3", "R4", "R5", "RUN:",
                        "ESCALATION:", "deadend:",
                        "volume_change_mm3", "needs_human"):
            self.assertIn(keyword, text)


def _tmp_db(test):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    patcher = patch.object(project_memory, "DB_PATH", Path(tmp.name))
    patcher.start()
    test.addCleanup(patcher.stop)
    test.addCleanup(lambda: Path(tmp.name).unlink(missing_ok=True))


class FactsSinceTests(unittest.TestCase):
    def test_filters_by_time_and_status(self):
        import time
        _tmp_db(self)
        first = remember_fact("moonman", "old", "o", "verified", "")
        self.assertIn("Recorded", first)
        time.sleep(0.02)
        since = project_memory._now()
        time.sleep(0.02)
        remember_fact("moonman", "new-a", "a", "assumption", "")
        remember_fact("moonman", "new-v", "v", "verified", "")
        rows = facts_since("moonman", since)
        self.assertEqual({r["subject"] for r in rows},
                         {"new-a", "new-v"})
        rows = facts_since("moonman", since, status="assumption")
        self.assertEqual([r["subject"] for r in rows], ["new-a"])


class SettledTests(unittest.TestCase):
    def test_deadend_subject_counts_as_settled(self):
        with patch.object(runner, "recall_facts", return_value=[
                {"subject": "deadend: horn PCD", "fact": "tried x",
                 "status": "failed", "provenance": "", "updated_at": ""}]):
            self.assertTrue(runner.is_settled("moonman", "horn PCD"))

    def test_unrelated_facts_do_not_settle(self):
        with patch.object(runner, "recall_facts", return_value=[
                {"subject": "tray holes", "fact": "d4.5",
                 "status": "verified", "provenance": "",
                 "updated_at": ""}]):
            self.assertFalse(runner.is_settled("moonman", "horn PCD"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
