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
