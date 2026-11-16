# labelled_pairs.jsonl — how this set was made

240 objective/status pairs: 20 objectives x 12 statuses, half on-task.

It replaces the original 60-pair set behind the figures in the top-level
README (AUC 0.332, r = 0.934). That set and its scripts were never
committed and could not be recovered, so those figures cannot be re-run.

## Design, fixed before any scoring

| kind | label | what it is | per objective |
|------|-------|------------|---------------|
| `on_echo` | on_task | on-task, reusing the objective's words | 3 |
| `on_para` | on_task | on-task, described in different words | 3 |
| `off_unrelated` | off_task | unrelated work | 3 |
| `off_reversal` | off_task | same words, but undoing, removing, disabling or arguing against the objective | 3 |

- `objective_id` is the cluster: statuses sharing an objective are not
  independent, so intervals resample whole objectives.
- `split`: odd-numbered objectives are `dev`, even-numbered are `test`.
  Any new scorer is developed on `dev` only and reported once on `test`.
- Score direction: higher score = on-task.

## What this set is and is not

- It is a **designed stress set**. Every pair was written by an AI
  assistant (Claude) to fit its kind, and the label follows from the kind.
  No human labelled it. The author knew how the matcher fails.
- It is **not a sample of real agent traffic**. An equal mix of the four
  kinds is a design choice, not an observed rate, so the pooled AUC is a
  property of this mix. The per-kind results are the ones to read.
- The file was committed before the matcher was run on it. The commit
  history shows the order.

# mutation_pairs.jsonl

120 statuses on 12 further objectives, used only to test the reversal
check (`warden/reversal.py`). Design, classes and decision rule are in
`PLAN.md` (Plan 2); results are in `RESULTS.md`, section 6.

Each objective has five reversals, built by a named mutation (antonym verb,
explicit undo, abandonment, substitution, implicit contradiction), and five
non-reversals, including on-task work that legitimately uses removal
wording. Written by the same AI author after the check was frozen and
before it was scored; labels follow from the class.
