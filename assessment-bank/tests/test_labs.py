"""Reference solutions for the eight labs. The bank only ships the tests, not these answers."""

from assessment_bank.bank import labs_dir, load_modules
from assessment_bank.grading import grade_lab

SOLUTIONS = {
    "foundations-lab-tokens": (
        "def estimate_tokens(text):\n"
        "    if not text:\n"
        "        return 0\n"
        "    return max(1, len(text) // 4)\n"
    ),
    "frameworks-lab-route": (
        "def route(text):\n"
        "    low = text.lower()\n"
        "    if 'invoice' in low or 'refund' in low:\n"
        "        return 'billing'\n"
        "    if 'vpn' in low or 'password' in low:\n"
        "        return 'tech'\n"
        "    return 'general'\n"
    ),
    "llm-lab-json": (
        "import json\n"
        "def parse_choice(text):\n"
        "    start, end = text.find('{'), text.rfind('}')\n"
        "    if start < 0 or end < start:\n"
        "        return None\n"
        "    try:\n"
        "        value = json.loads(text[start:end + 1]).get('choice')\n"
        "    except json.JSONDecodeError:\n"
        "        return None\n"
        "    return value if isinstance(value, str) else None\n"
    ),
    "rag-lab-citations": (
        "def sentences_are_cited(text):\n"
        "    if text == '':\n"
        "        return True\n"
        "    parts = [p for p in text.split('. ') if p]\n"
        "    return all('[' in p and ']' in p for p in parts)\n"
    ),
    "agentic-lab-stop": "def should_stop(steps, max_steps):\n    return steps >= max_steps\n",
    "trust-lab-redact": (
        "import re\n"
        "def redact_emails(text):\n"
        "    return re.sub(r'[A-Za-z0-9.-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}', '[redacted]', text)\n"
    ),
    "customization-lab-choice": (
        "def choose(labelled_examples):\n"
        "    return 'prompt' if labelled_examples < 50 else 'finetune'\n"
    ),
    "production-lab-health": "def health():\n    return {'status': 'ok'}\n",
}


def test_reference_solutions_pass_and_a_broken_one_fails():
    labs = {lab.id: lab for module in load_modules() for lab in module.labs}
    assert set(labs) == set(SOLUTIONS)
    root = labs_dir()
    for lab_id, code in SOLUTIONS.items():
        grade = grade_lab(labs[lab_id], code, root)
        assert grade.passed, grade.summary
        assert grade.points == grade.max_points
    broken = grade_lab(
        labs["foundations-lab-tokens"],
        "def estimate_tokens(text):\n    return 1\n",
        root,
    )
    assert not broken.passed and broken.points == 0


def test_syntax_errors_do_not_run():
    lab = next(
        item
        for module in load_modules()
        for item in module.labs
        if item.id == "production-lab-health"
    )
    grade = grade_lab(lab, "def health(:\n", labs_dir())
    assert not grade.passed
    assert "syntax error" in grade.summary
