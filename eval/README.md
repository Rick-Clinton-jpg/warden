# eval/

| File | What it is |
|------|------------|
| `labelled_pairs.jsonl` | 240 labelled objective/status pairs |
| `DATASET.md` | How the set was designed and what it does not show |
| `PLAN.md` | Analysis plan and replacement gate, committed before scoring |
| `RESULTS.md` | Results, hand check, assumptions |
| `baseline.json` | Frozen output of `warden eval` on the set |
| `candidates.py` | Experimental scorers; not used by WARDEN |

```bash
warden eval eval/labelled_pairs.jsonl                 # report
warden eval eval/labelled_pairs.jsonl --split test    # one split
warden eval eval/labelled_pairs.jsonl --json > eval/baseline.json
```

`tests/test_eval_baseline.py` recomputes the report on every CI run and
fails if any number moves. If the matcher or the data changes on purpose,
regenerate `baseline.json` in the same commit.

Row format:

```json
{"id": "o01-on_echo-1", "objective_id": "o01", "split": "dev", "kind": "on_echo",
 "objective": "...", "status": "...", "label": "on_task"}
```

`label` is `on_task` or `off_task`. `objective_id`, `kind` and `split` are optional.
