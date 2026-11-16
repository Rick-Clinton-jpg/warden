# Evaluation data

Put the hand-labelled pairs here as `labelled_pairs.jsonl`, one per line:

```json
{"id": "p01", "objective": "...", "status": "...", "label": "on_task"}
```

`label` is the human ground truth: `on_task` or `off_task`.

```bash
warden eval eval/labelled_pairs.jsonl                         # report
warden eval eval/labelled_pairs.jsonl --json > eval/baseline.json   # freeze it
```

Once both files are committed, `tests/test_eval_baseline.py` recomputes the
report on every CI run and fails if any number moves, so the figures quoted
in the top-level README stay tied to this data and this code.
