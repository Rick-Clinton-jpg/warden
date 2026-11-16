# Results — 16 November 2026

Data: `labelled_pairs.jsonl` (240 pairs, 20 objectives, SHA-256 `8212e91c…fd0d4e`).
Plan: `PLAN.md`, committed before scoring. Regime: SMALL (20 clusters). alpha = 0.05.
Reproduce the first table with `warden eval eval/labelled_pairs.jsonl`
(frozen in `baseline.json`, re-checked by CI).

## 1. Shipped raters, all 240 pairs (confirmatory)

| Rater | Pooled AUC | 95% CI (objectives resampled) | DeLong 95% CI | Sign-flip p | Holm p |
|---|---|---|---|---|---|
| A — word-Jaccard | 0.529 | 0.507 – 0.552 | 0.460 – 0.598 | 0.034 | 0.068 |
| B — char-trigram | 0.499 | 0.473 – 0.526 | 0.425 – 0.573 | 0.590 | 0.590 |

**The pre-committed hypothesis (pooled AUC below 0.5) is not supported.** On a
set with equal shares of the four kinds, both raters sit at chance. Neither
differs from 0.5 at the 5% level after Holm correction.

The pooled number hides what is happening. By kind:

| On-task kind vs off-task kind | Rater A AUC (95% CI) | Rater B AUC (95% CI) |
|---|---|---|
| same words vs unrelated work | 1.000 (1.000 – 1.000) | 1.000 (1.000 – 1.000) |
| same words vs reversal | 0.599 (0.512 – 0.688) | 0.600 (0.535 – 0.669) |
| different words vs unrelated work | 0.516 (0.483 – 0.550) | 0.397 (0.305 – 0.488) |
| different words vs reversal | **0.000** (0.000 – 0.000) | **0.000** (0.000 – 0.000) |

Final tag at the shipped thresholds:

| Kind | MATCH | DRIFT | UNCLEAR | DIVERGENT |
|---|---|---|---|---|
| on-task, same words | 53 | 0 | 1 | 6 |
| on-task, different words | 0 | **57** | 0 | 3 |
| off-task, unrelated | 0 | 58 | 0 | 2 |
| off-task, reversal | **55** | 0 | 3 | 2 |

- Reversal tagged MATCH: 55 of 60 (Wilson 95% CI 82% – 96%).
- On-task work in different words tagged DRIFT: 57 of 60 (86% – 98%).
- Raters A and B: Pearson r = 0.951 (0.936 – 0.966). AUC difference
  0.030 (DeLong p = 0.068).

**Reading.** The matcher measures word reuse. It is perfect when on-task work
reuses the objective's words and off-task work does not, and exactly wrong
when on-task work is paraphrased and off-task work reuses the words. The
pooled AUC is therefore set by the mix of kinds in the test set, not by the
matcher. The original 0.332 (60 pairs, 5 objectives, set not recoverable)
is consistent with a set weighted toward the last row; it cannot be re-run.

## 2. Candidate scorers (exploratory; developed on `dev`, scored once on `test`)

`test` = 120 pairs, 10 objectives. Code: `candidates.py`, frozen in the
commit before this scoring.

| Scorer | Pooled AUC (95% CI) | different words vs unrelated (95% CI) |
|---|---|---|
| containment | 0.544 (0.519 – 0.571) | 0.516 (0.465 – 0.567) |
| directional (containment, negated on opposing wording) | 0.797 (0.723 – 0.862) | 0.516 (0.465 – 0.567) |

Gate (PLAN.md): replace the matcher only if both intervals exclude 0.5.

- Gate 2, pooled AUC: **passed** by `directional`.
- Gate 1, different words vs unrelated: **failed** by both (interval spans 0.5).

**Decision: the matcher is not replaced.** No scorer built on shared words
can tell paraphrased on-task work from unrelated work, because neither
shares words with the objective.

The opposing-wording check on its own, on `test`:
- reversals caught: 25 of 30 (Wilson 95% CI 66% – 93%);
- on-task statuses wrongly flagged: 3 of 60 (2% – 14%);
- unrelated statuses flagged: 0 of 30.

## 3. Hand check

Pooled AUC for Rater A = (sum of the four kind-vs-kind AUCs) / 4, because
each kind has 60 pairs: (1.000 + 0.5994 + 0.5164 + 0.000) / 4 = 0.5290.

## 4. Assumptions

| Assumption | Status |
|---|---|
| Score direction: higher = on-task | checked (same-words vs unrelated = 1.000) |
| Objectives are independent clusters | assumed (all written by one author) |
| Labels are correct | by construction from `kind`; **not** independently labelled |
| Bootstrap interval is valid with 20 (or 10) clusters | no — it runs narrow; read as optimistic |
| The equal mix of kinds reflects real traffic | no — there is no real traffic to sample |

## 5. What would change the conclusion

- A real sample of agent statuses with a different mix would move the pooled
  AUC anywhere between 0 and 1; the per-kind rows would not move much.
- An independent labeller disagreeing with `kind`-derived labels on many
  pairs would weaken every row.
- A scorer passing Gate 1 needs a signal other than shared words (meaning,
  or what the agent actually did), which this dependency-free design lacks.
