# Analysis plan — committed before the set was scored

Regime: SMALL (20 objectives = 20 clusters). alpha = 0.05.

## Hypothesis
Each shipped rater ranks off-task statuses above on-task ones on this set
(AUC < 0.5). Falsified for a rater if its 95% interval reaches 0.5.

## Confirmatory (Holm-corrected, m = 2), on all 240 pairs
1. Rater A (word-Jaccard) pooled AUC vs 0.5.
2. Rater B (char-trigram) pooled AUC vs 0.5.

Interval: bootstrap resampling whole objectives (10,000 resamples, fixed
seed). p-value: sign-flip test on the 20 per-objective (AUC - 0.5) values.
Secondary: DeLong interval, which ignores clustering.

## Exploratory (Benjamini-Hochberg where p-values are given)
- AUC for each on-kind vs each off-kind (4 contrasts per scorer).
- Rater A vs Rater B: AUC difference, Pearson r of scores.
- Final tag by kind, at the shipped thresholds (0.35 / 0.15, 0.30 / 0.12).

## Candidate scorers
Developed on `split = dev` only, then scored once on `split = test`.

A candidate replaces the shipped matcher only if, on `test`, BOTH hold:
1. `on_para` vs `off_unrelated` AUC: 95% interval lower bound > 0.5.
2. pooled AUC: 95% interval lower bound > 0.5.

Gate 1 is the real test. A scorer that cannot tell on-task work in
different words from unrelated work still raises a false DRIFT on normal
traffic, whatever its pooled AUC. If no candidate passes, the matcher is
not replaced and the project stays on hold.

---

# Plan 2 — reversal warning (committed before the mutation set was written or scored)

`warden/reversal.py` is frozen in this commit. It was developed on all 240
pairs of `labelled_pairs.jsonl`, which therefore cannot test it
(on that file: 54 of 60 reversals flagged, 0 of 180 other statuses flagged).

## Test set: `mutation_pairs.jsonl`
12 objectives that appear nowhere in `labelled_pairs.jsonl`; 4 of them
reductive ("Remove ...", "Reduce ..."). Per objective, 10 statuses:

| class | label | what it is |
|---|---|---|
| `M1_antonym` | reversal | on-task status with its verb swapped for the opposite |
| `M2_undo` | reversal | explicit undo of the work (revert, roll back, undo) |
| `M3_abandon` | reversal | negation or abandonment (stop, no longer, give up, cancel) |
| `M4_substitute` | reversal | does something else in place of the objective |
| `M5_implicit` | reversal | contradicts the objective with no undo wording at all |
| `C1_base` | not_reversal | plain on-task status |
| `C2_reworded` | not_reversal | the same on-task work, reworded |
| `C3_undo_word_on_task` (x2) | not_reversal | on-task work that legitimately uses remove/delete/drop/revert wording |
| `C4_undo_word_unrelated` | not_reversal | unrelated work that uses undo wording |

M5 is included knowing the check cannot catch it; C3 and C4 are included
because they are where a wording check should raise false flags.

## Measures
- Recall: flagged reversals / 60, overall and per mutation class.
- False-flag rate: flagged non-reversals / 60, overall and per control class.
- Wilson 95% intervals, and a bootstrap over objectives for the two totals.

## Decision rule
The check stays on by default only if, on this set, recall >= 0.60 AND
false-flag rate <= 0.10. Otherwise it ships off by default
(`--reversal-check` to opt in). Scored once; no changes to the check after.
