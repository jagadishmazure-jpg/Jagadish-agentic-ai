# `scripts/`

Helpers that keep the documentation honest. CI runs `render_docs.py --check`.

| File | What it does |
|---|---|
| [`render_docs.py`](render_docs.py) | Fills `<!-- output: ... -->`, `<!-- output-md: ... -->` and `<!-- code: ... -->` blocks in every Markdown file with real command output and current source; `--check` fails when any block is stale |
| [`doc_tables.py`](doc_tables.py) | Prints README sections straight from a project's `doctrine.yaml` (steps, planes, systems, corpora, identities, stop conditions, playbook, chaos, thresholds, KPIs, Azure mapping, test counts) |
| [`component_demos.py`](component_demos.py) | Small offline demos of the shared components whose output is pasted into `docs/components/` |

```bash
python scripts/render_docs.py           # refresh every block
python scripts/render_docs.py --check   # what CI runs
python scripts/doc_tables.py 03 all     # preview a project's generated sections
```
