"""Documentation standard: full section set, folder READMEs, guides, ownership, no placeholders.

The content of pasted output and code excerpts is checked by ``scripts/render_docs.py --check``
in CI (it re-runs every command); these tests check the structure.
"""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SECTIONS = [
    "Purpose", "Architecture", "How it works", "Key files", "Code excerpts", "Configuration",
    "Commands", "Real output", "Tests and eval gates", "Guardrails", "Security and governance",
    "Observability", "Failure modes", "Mapping to Azure services", "Limitations",
    "Interview talking points", "Adopt this",
]  # fmt: skip
PROJECT_DOCS = sorted(ROOT.glob("projects/[0-9][0-9]-*/README.md"))
COMPONENT_DOCS = sorted(p for p in (ROOT / "docs/components").glob("*.md") if p.name != "README.md")
FULL_DOCS = PROJECT_DOCS + COMPONENT_DOCS
SKIP = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".terraform"}


def tracked_dirs() -> list[Path]:
    files = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.split()  # fmt: skip
    return sorted({(ROOT / f).parent for f in files if not SKIP & set(Path(f).parts)})


def test_counts():
    assert len(PROJECT_DOCS) == 21
    assert len(COMPONENT_DOCS) == 11


@pytest.mark.parametrize("doc", FULL_DOCS, ids=lambda p: str(p.relative_to(ROOT)))
def test_full_doc_has_every_section_in_order(doc):
    t = doc.read_text()
    pos = [t.find(f"\n## {i}. {s}\n") for i, s in enumerate(SECTIONS, 1)]
    assert all(p >= 0 for p in pos), [s for s, p in zip(SECTIONS, pos, strict=True) if p < 0]
    assert pos == sorted(pos)
    assert "```mermaid" in t, "architecture needs a mermaid diagram"
    assert "<!-- output" in t, "real output must be pasted by render_docs.py"
    assert "<!-- code:" in t, "code excerpts must be pasted by render_docs.py"
    adopt = t[pos[-1] :].split("\n", 2)[2].strip()
    assert len(adopt) > 200


def test_every_folder_has_a_readme():
    dirs = [d for d in tracked_dirs() if d != ROOT / ".github"]
    missing = [str(d.relative_to(ROOT)) for d in dirs if not (d / "README.md").exists()]
    assert not missing
    # No .github/README.md: GitHub would show it instead of the root README.
    assert not (ROOT / ".github/README.md").exists()


def test_guides_and_ownership():
    for f in ("docs/implementation-guide.md", "docs/adopt-this.md", "docs/best-practices.md"):
        assert (ROOT / f).exists(), f
    assert "* @jagadishmazure-jpg" in (ROOT / ".github/CODEOWNERS").read_text()
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "scripts/render_docs.py --check" in ci


def test_no_placeholders_or_todos():
    for p in ROOT.rglob("*.md"):
        if SKIP & set(p.parts):
            continue
        t = p.read_text()
        for word in ("TODO", "TBD", "FIXME", "lorem ipsum", "coming soon"):
            assert word not in t, f"{word} in {p.relative_to(ROOT)}"


def test_readme_test_count_is_current():
    out = subprocess.run(
        ["python", "-m", "pytest", "--co", "-q", "-q"], cwd=ROOT, capture_output=True, text=True
    ).stdout  # fmt: skip
    total = sum(int(n) for n in re.findall(r"\.py: (\d+)$", out, re.M))
    m = re.search(r"\*\*(\d+) automated tests\*\*", (ROOT / "README.md").read_text())
    assert m and int(m.group(1)) == total, (m and m.group(1), total)
