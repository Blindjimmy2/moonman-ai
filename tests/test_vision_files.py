"""Tests for sharing local image files with Moon Man. No network needed.

Covers: image paths found in pasted text (quoted, or bare Windows /
POSIX paths with spaces), missing and non-image paths ignored, per-turn
count and size caps, and ask_moonman sending the file bytes as an
image_url part without touching the camera.

Run from the project root:
    python tests/test_vision_files.py
"""

import base64
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(__file__.rsplit("tests", 1)[0] + "src"))

import agent


# Smallest valid PNG (1x1), enough for byte round-trip checks.
TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _make_image(directory, name="bracket photo.png"):
    path = os.path.join(directory, name)
    with open(path, "wb") as handle:
        handle.write(TINY_PNG)
    return path


def _text_response(text):
    message = MagicMock()
    message.tool_calls = []
    message.content = text
    response = MagicMock()
    response.choices = [MagicMock(message=message)]
    return response


class FindImagePathsTests(unittest.TestCase):
    def test_bare_path_with_spaces_found(self):
        with tempfile.TemporaryDirectory(prefix="moon man pics ") as tmp:
            image = _make_image(tmp)
            found = agent.find_image_paths("make this " + image + " please")
        self.assertEqual(found, [image])

    def test_quoted_path_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = _make_image(tmp)
            found = agent.find_image_paths('see "%s" ok?' % image)
        self.assertEqual(found, [image])

    def test_missing_file_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            ghost = os.path.join(tmp, "nope.png")
            self.assertEqual(agent.find_image_paths("see " + ghost), [])

    def test_non_image_file_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = os.path.join(tmp, "notes.txt")
            Path(text).write_text("no picture here", encoding="utf-8")
            self.assertEqual(
                agent.find_image_paths('see "%s"' % text), [])

    def test_count_capped_per_turn(self):
        with tempfile.TemporaryDirectory() as tmp:
            images = [_make_image(tmp, "shot %d.png" % i) for i in range(6)]
            found = agent.find_image_paths("see " + " ".join(
                '"%s"' % p for p in images))
        self.assertEqual(len(found), agent.MAX_VISION_IMAGES)
        self.assertEqual(found, images[:agent.MAX_VISION_IMAGES])

    def test_plain_text_finds_nothing(self):
        self.assertEqual(
            agent.find_image_paths("what do you see over there?"), [])


class AttachFileImagesTests(unittest.TestCase):
    def test_attached_bytes_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = _make_image(tmp)
            parts = [{"type": "text", "text": "see " + image}]
            attached = agent.attach_file_images(parts, "see " + image)
        self.assertEqual(attached, [image])
        self.assertEqual(len(parts), 2)
        url = parts[1]["image_url"]["url"]
        self.assertTrue(url.startswith("data:image/png;base64,"))
        self.assertEqual(
            base64.b64decode(url.split(",", 1)[1]), TINY_PNG)

    def test_oversize_image_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = _make_image(tmp)
            parts = [{"type": "text", "text": "see " + image}]
            with patch.object(agent, "MAX_VISION_IMAGE_BYTES", 10):
                attached = agent.attach_file_images(parts, "see " + image)
        self.assertEqual(attached, [])
        self.assertEqual(len(parts), 1)


class AskMoonmanFileVisionTests(unittest.TestCase):
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

    def test_pasted_path_sent_as_image_without_camera(self):
        backup = list(agent.history)
        agent.history.clear()
        self.addCleanup(lambda: (agent.history.clear(),
                                 agent.history.extend(backup)))
        with tempfile.TemporaryDirectory(prefix="moon man pics ") as tmp:
            image = _make_image(tmp)
            question = "can you make this? " + image
            with patch.object(agent.client.chat.completions, "create",
                              return_value=_text_response("Nice bracket.")) \
                    as mock_create:
                with patch.object(agent, "capture_image") as mock_camera:
                    answer = agent.ask_moonman(question)
        self.assertEqual(answer, "Nice bracket.")
        mock_camera.assert_not_called()
        sent = mock_create.call_args.kwargs["messages"][-1]
        self.assertEqual(sent["role"], "user")
        images = [p for p in sent["content"] if p.get("type") == "image_url"]
        self.assertEqual(len(images), 1)
        self.assertTrue(images[0]["image_url"]["url"].startswith(
            "data:image/png;base64,"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
