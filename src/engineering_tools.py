import ast

from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = (ROOT / "moonman_engineering").resolve()
WORKSPACE.mkdir(exist_ok=True)

def _safe_path(path):
    p = (WORKSPACE / path).resolve()
    if not p.is_relative_to(WORKSPACE):
        raise ValueError("Path outside engineering workspace")
    return p

def engineering_list(path="."):
    p = _safe_path(path)
    if not p.is_dir():
        raise ValueError("Not a directory")
    return {"files": [
        {"name": x.name, "directory": x.is_dir()}
        for x in sorted(p.iterdir())[:100]
        if not x.is_symlink()
    ]}

def engineering_read(path):
    p = _safe_path(path)
    if not p.is_file():
        raise FileNotFoundError(str(p))
    if p.stat().st_size > 100000:
        raise ValueError("File too large")
    return {"path": str(p), "content": p.read_text(encoding="utf-8")}

def engineering_write(path, content):
    p = _safe_path(path)
    if p.suffix.lower() not in (".py", ".txt", ".json", ".md"):
        raise ValueError("Unsupported file type")
    if len(content) > 100000:
        raise ValueError("Content too large")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"saved": str(p)}

def engineering_test(path):
    p = _safe_path(path)
    if p.suffix.lower() != ".py" or not p.is_file():
        raise ValueError("Python file required")
    ast.parse(p.read_text(encoding="utf-8"))
    return {"syntax": "PASS", "file": str(p)}

