"""Offline tests for the Pocket TTS workers. No models, no audio.

Parses the sources (no import side effects: torch/pocket_tts live only in
the voice-test interpreter). Pure helpers are extracted and executed for
real. Run:
  python test_voice_workers.py
"""

import ast
import re
from pathlib import Path

HERE = Path(__file__).parent
STREAM = (HERE / "voice_worker.py").read_text(encoding="utf-8")
FILEW = (HERE / "pocket_file_worker.py").read_text(encoding="utf-8")

# Both workers use the same established British voice.
for name, src in (("voice_worker", STREAM), ("pocket_file_worker", FILEW)):
    found = re.search(r'^VOICE = "([^"]+)"', src, re.M)
    assert found, name + " has no VOICE"
    assert found.group(1) == "stuart_bell", (name, found.group(1))
print("PASS same voice (stuart_bell) in both workers")

# Both split long replies into bounded chunks with a fresh stream per chunk
# (one long generation lets the voice drift off the prompt).
for name, src in (("voice_worker", STREAM), ("pocket_file_worker", FILEW)):
    assert "def split_chunks" in src, name + " has no split_chunks"
    assert "MAX_CHUNK" in src, name + " has no MAX_CHUNK"
print("PASS chunking present in both workers")

sizes = sorted(set(re.findall(r"^MAX_CHUNK = (\d+)", STREAM + FILEW, re.M)))
assert sizes, "no MAX_CHUNK found"
print("PASS chunk sizes:", ", ".join(sizes))

# Streaming worker renders one stream per chunk with gaps between chunks.
assert "for index, piece in enumerate(chunks)" in STREAM
assert "generate_audio_stream(voice, piece)" in STREAM
assert "stream.write(gap)" in STREAM
print("PASS streaming worker renders per-chunk streams with gaps")

# Inline-code cleanup keeps the spoken word, not a literal backslash.
assert 'r"\\1"' in STREAM, "inline-code substitution broken"
assert 'r"\\\\1"' not in STREAM, "literal backslash-one regression"
print("PASS inline-code cleanup")


def _load(name, src):
    tree = ast.parse(src)
    wanted = {"split_chunks", "clean_speech"}
    fns = [n for n in tree.body if getattr(n, "name", None) in wanted]
    assert len(fns) == 2, name
    ns = {"re": re, "MAX_CHUNK": 400}
    exec(compile(ast.Module(body=fns, type_ignores=[]), name, "exec"), ns)
    return ns["split_chunks"], ns["clean_speech"]


SPLIT_S, CLEAN_S = _load("voice_worker", STREAM)
SPLIT_F, CLEAN_F = _load("pocket_file_worker", FILEW)

# Markdown never reaches the voice.
SAMPLE = "**Bold** __x__ and `code` plus *starred words here\n# Title\n- item"
WANT = "Bold x and code plus starred words here Title item"
for name, clean in (("voice_worker", CLEAN_S), ("pocket_file_worker", CLEAN_F)):
    got = clean(SAMPLE)
    assert got == WANT, (name, repr(got))
    assert clean("```py\nx()\n``` hi") == "hi", name
print("PASS markdown stripped in both workers")

# Long replies split on sentences, bounded, lossless, identical.
TEXT = ("This is sentence one. " * 30) + ("NoPunctuation" * 50)
chunks_s, chunks_f = SPLIT_S(TEXT), SPLIT_F(TEXT)
assert chunks_s == chunks_f, (chunks_s, chunks_f)
assert all(len(c) <= 400 for c in chunks_s), [len(c) for c in chunks_s]
flat = "".join("".join(chunks_s).split())
assert flat == "".join(TEXT.split()), "chars lost"
print("PASS chunk parity + bounds:", [len(c) for c in chunks_s])

print("ALL VOICE WORKER TESTS PASSED")
