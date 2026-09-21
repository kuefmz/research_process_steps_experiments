# Research Process Steps Experiments

Deterministic, explainable heuristics for identifying which **research process step(s)** individual files in a GitHub repository support.

The implementation uses **no AI**: no LLMs, embeddings, machine-learning models, or probabilistic classifiers. Labels are produced only from explicit, auditable path/filename rules and regular-expression content rules.

## Research process steps

The detector is multi-label and supports six steps:

- **Collection** — acquisition or generation of raw research data.
- **Processing** — parsing, cleaning, transformation, extraction, or preparation.
- **Implementation** — implementation, packaging, execution, or software verification.
- **Experimentation** — scripts/configuration/artifacts used to run research experiments.
- **Evaluation** — scientific benchmarking, metrics, comparisons, or ablations.
- **Dissemination** — documentation, citation metadata, publications, or distribution.

A file may support more than one step. If no rule provides sufficient evidence, the file is deliberately returned as `unclassified`.

## Python usage

```python
from research_process_steps import analyze_github_repository

result = analyze_github_repository(
    "https://github.com/KnowledgeCaptureAndDiscovery/somef"
)

for file in result["files"]:
    print(file["path"], file["steps"])
```

Each file keeps the exact evidence that caused a label:

```python
file = result["files"][0]
print(file["steps"])
print(file["scores"])
print(file["evidence"])
```

Example shape:

```json
{
  "path": "experiments/evaluate_model.py",
  "steps": ["experimentation", "evaluation"],
  "unclassified": false,
  "scores": {
    "experimentation": 3,
    "evaluation": 3
  },
  "evidence": [
    {
      "rule_id": "EXP_PATH_EXPERIMENT_DIR",
      "step": "experimentation",
      "source": "path",
      "weight": 3
    },
    {
      "rule_id": "EVA_PATH_EVAL_FILE",
      "step": "evaluation",
      "source": "path",
      "weight": 3
    }
  ]
}
```

## CLI

Install locally:

```bash
python -m pip install -e .
```

Analyze a repository:

```bash
research-process-steps https://github.com/KnowledgeCaptureAndDiscovery/somef
```

Write the complete per-file result to JSON:

```bash
research-process-steps \
  https://github.com/KnowledgeCaptureAndDiscovery/somef \
  -o somef_steps.json
```

An optional GitHub token can be supplied through `GITHUB_TOKEN` or `--token`.

## Heuristic design

Rules have a stable ID, a process step, an evidence source, and a weight.

- **3 — strong evidence:** explicit structural/file signal such as `experiments/` or `evaluation/benchmark.py`.
- **2 — medium evidence:** conventional but less specific signal such as a README.
- **1 — weak evidence:** deterministic content regex.

The current detection threshold is **2**, so a single incidental content keyword cannot assign a process step.

Path and filename evidence is primary. Content inspection is secondary and is performed only on likely text/source files below a configurable size threshold.

### Evaluation vs software tests

Ordinary software tests (`tests/`, `test_*.py`, etc.) are classified as **Implementation**, not scientific **Evaluation**. Evaluation requires evidence such as explicit benchmark/evaluation/metric/ablation artifacts.

## Output structure

The returned JSON contains:

- `repository`: repository/ref and file count.
- `method`: method metadata, including `uses_ai: false`.
- `summary`: number of files detected for each step and number unclassified.
- `files`: one record for **every repository file**, including labels, score, matched rule IDs, and evidence.

This evidence-preserving output is intended for later validation against a manually annotated corpus.

## Tests

```bash
python -m pip install pytest
pytest
```

The initial tests cover all six process steps, multi-label behavior, unclassified files, and the distinction between scientific evaluation and software unit tests.
