"""Keep pasted output and code excerpts in the Markdown docs honest.

Markdown files contain blocks like::

    <!-- output: python projects/03-refund-agent/run.py -->
    ```text
    ...whatever that command prints...
    ```
    <!-- /output -->

    <!-- output-md: python scripts/doc_tables.py 03 playbook -->
    ...a Markdown table printed by the command, pasted as-is...
    <!-- /output -->

    <!-- code: shared/llm.py::azure_auth_kwargs -->
    ```python
    ...the current source of that top-level function, class or constant...
    ```
    <!-- /code -->

``output`` runs the shell command from the repository root (offline: ``LLM_PROVIDER=mock``) and
pastes its stdout. Run-specific values (trace and span ids) are masked so the text is stable.
``code`` pastes a Python definition (``path::name`` or ``path::Class.method``), the tail of one from the first line containing
some text (``path::name|StateGraph(``), a line range (``path:10-30``) or a whole file.

    python scripts/render_docs.py          # rewrite every block
    python scripts/render_docs.py --check  # exit 1 if any block is stale (CI runs this)
    python scripts/render_docs.py docs/x.md --check   # only some files
"""

from __future__ import annotations

import ast
import difflib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = {".git", ".venv", "node_modules", ".pytest_cache", ".terraform", "__pycache__"}
OUTPUT = re.compile(
    r"(<!-- (?P<kind>output|output-md): (?P<cmd>.+?) -->\n)(?P<body>.*?)(<!-- /output -->)", re.S
)
CODE = re.compile(r"(<!-- code: (?P<ref>[^>]+?) -->\n)(?P<body>.*?)(<!-- /code -->)", re.S)
LANG = {".py": "python", ".yaml": "yaml", ".yml": "yaml", ".tf": "hcl", ".bicep": "bicep", ".json": "json",
        ".sh": "bash", ".toml": "toml", ".kql": "kusto", ".sql": "sql", ".mmd": "mermaid"}  # fmt: skip
MASKS = [
    (re.compile(r"\b[0-9a-f]{32}\b"), "<trace-id>"),
    (re.compile(r"\b[0-9a-f]{16}\b"), "<span-id>"),
]
_cache: dict[str, str] = {}


def run(cmd: str) -> str:
    if cmd not in _cache:
        env = {**os.environ, "LLM_PROVIDER": "mock", "PYTHONHASHSEED": "0", "NO_COLOR": "1", "COLUMNS": "120",
               "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1",
               "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}"}  # fmt: skip
        for var in (
            "AZURE_OPENAI_ENDPOINT",
            "AZURE_OPENAI_API_KEY",
            "OPENAI_API_KEY",
            "OTEL_CONSOLE",
        ):
            env.pop(var, None)
        r = subprocess.run(
            ["bash", "-c", cmd], cwd=ROOT, env=env, capture_output=True, text=True, timeout=600
        )
        if r.returncode != 0:
            raise SystemExit(
                f"command failed ({r.returncode}): {cmd}\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}"
            )
        out = r.stdout.replace(str(ROOT) + "/", "").replace(str(ROOT), ".")
        for rx, sub in MASKS:
            out = rx.sub(sub, out)
        _cache[cmd] = "\n".join(line.rstrip() for line in out.strip("\n").splitlines())
    return _cache[cmd]


def excerpt(ref: str) -> tuple[str, str]:
    ref, _, start_at = ref.partition("|")
    path, _, name = ref.partition("::")
    m = re.fullmatch(r"(.+):(\d+)-(\d+)", path) if not name else None
    if m:
        path = m.group(1)
    p = ROOT / path
    src = p.read_text()
    lang = LANG.get(p.suffix, "text")
    if m:
        lines = src.splitlines()[int(m.group(2)) - 1 : int(m.group(3))]
        return lang, "\n".join(lines).rstrip()
    if not name:
        return lang, src.rstrip()
    tree = ast.parse(src)
    lines = src.splitlines()
    body = tree.body
    if "." in name:  # Class.method
        cls, name = name.split(".", 1)
        body = next(n.body for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
    for node in body:
        names = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names = [node.name]
        elif isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        if name in names:
            start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
            block = lines[start - 1 : node.end_lineno]
            if body is not tree.body:
                pad = len(block[0]) - len(block[0].lstrip())
                block = [x[pad:] for x in block]
            if (
                start_at
            ):  # only the tail of a long definition, from the first line containing start_at
                idx = next((i for i, line in enumerate(block) if start_at in line), None)
                if idx is None:
                    raise SystemExit(f"{start_at!r} not found in {path}::{name}")
                tail = block[idx:]
                indent = min(len(x) - len(x.lstrip()) for x in tail if x.strip())
                block = [f"# {name}() continued: wiring", *(x[indent:] for x in tail)]
            return lang, "\n".join(block).rstrip()
    raise SystemExit(f"{name} not found in {path}")


def render(text: str) -> str:
    def out(m: re.Match) -> str:
        body = run(m["cmd"])
        if m["kind"] == "output":
            body = f"```text\n{body}\n```"
        return f"{m.group(1)}{body}\n{m.group(5)}"

    def code(m: re.Match) -> str:
        lang, body = excerpt(m["ref"])
        return f"{m.group(1)}```{lang}\n{body}\n```\n{m.group(4)}"

    return CODE.sub(code, OUTPUT.sub(out, text))


def docs(args: list[str]) -> list[Path]:
    if args:
        return [ROOT / a for a in args]
    return sorted(p for p in ROOT.rglob("*.md") if not SKIP & set(p.relative_to(ROOT).parts))


def main(argv: list[str]) -> int:
    check = "--check" in argv
    stale = []
    for p in docs([a for a in argv if a != "--check"]):
        text = p.read_text()
        if "<!-- output" not in text and "<!-- code:" not in text:
            continue
        new = render(text)
        if new != text:
            stale.append(p.relative_to(ROOT))
            if check:  # show what drifted, so a CI failure is diagnosable from the log
                diff = difflib.unified_diff(
                    text.splitlines(),
                    new.splitlines(),
                    str(p.relative_to(ROOT)),
                    "rendered",
                    lineterm="",
                    n=1,
                )
                print("\n".join(list(diff)[:60]))
            if not check:
                p.write_text(new)
    verb = "stale" if check else "updated"
    print(f"{len(stale)} file(s) {verb}" + "".join(f"\n  {s}" for s in stale))
    return 1 if check and stale else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
