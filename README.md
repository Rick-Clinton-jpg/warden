# WARDEN

**Lightweight Agent Drift Detection & Audit System**

Version 0.2.0

> **ON HOLD — prototype stage, not production-ready.** Core detector found to have a fundamental scoring flaw; see [Known Issues / Limitations](#known-issues--limitations) below.

Warden is an external observer for long-running AI coding agents (Claude Code, Codex, and others).  
It does **not** control, rewrite, or interrupt the agent.  
It only:

1. Collects a single-line status the agent emits every N minutes  
2. Compares that status to the original objective  
3. Tags it `MATCH` / `DRIFT` / `UNCLEAR` / `DIVERGENT`, or `STALE` when the status is too old to score  
4. Writes a short note to an append-only NDJSON audit trail  

---

## Core Principle

> Observe only. Never intervene.

This is the product's identity.

---

## Known Issues / Limitations

**The core matcher measures word reuse, not whether the agent is on task.**
On a 240-pair labelled set (20 objectives, in [`eval/`](./eval)), what the
matcher gets right depends entirely on wording:

| On-task status | Off-task status | Rater A AUC |
|---|---|---|
| reuses the objective's words | unrelated work | 1.000 |
| reuses the objective's words | reverses the objective | 0.599 |
| different words | unrelated work | 0.516 |
| different words | reverses the objective | **0.000** |

An AUC of 0.000 is not noise — on that row the score is exactly
anti-correlated with ground truth. With equal shares of the four kinds the
pooled AUC is 0.529 (Rater A) and 0.499 (Rater B): chance. Any pooled figure
is a property of the mix in the test set, not of the matcher.

At the shipped thresholds, a status that reverses the objective is tagged
`MATCH` 55 times in 60, and on-task work described in different words is
tagged `DRIFT` 57 times in 60.

**Root cause.** The scorer measures vocabulary overlap, not directional
alignment. Reversing or deleting the objective's work can score as high or
higher than doing the correct work in different words. Example, against the
same objective: "Deleting the /score and /debug endpoints from the
IntentGraph API wrapper" scores MATCH (0.78), while "Wiring up FastAPI
routers and Pydantic response models for the two handlers" scores DRIFT
(0.06).

**No dependency-free replacement was found.** Two candidate scorers were
developed on half the objectives and scored once on the other half. The
better one reaches a pooled AUC of 0.797 by penalising undo wording, but
neither separates on-task work in different words from unrelated work
(AUC 0.516, interval spans 0.5) — the two share no words with the objective.
That needs a signal other than shared words.

**The dual-rater system is not independent.** Word-Jaccard and
trigram-Jaccard scores correlate at Pearson r = 0.951. Agreement between the
two raters is not corroboration, and their disagreement (the `DIVERGENT` tag)
is mostly threshold noise on a shared signal, not two independent checks
catching different failure modes.

**The status line may never arrive.** WARDEN depends on the agent emitting
`WARDEN_STATUS` on a schedule. An agent only produces text when it is
invoked and has no clock, so nothing guarantees it does. A status that is
old is now tagged `STALE` and not scored (see
[Status Freshness](#status-freshness-stale)), but a session that never
emits one produces only `UNCLEAR`.

**The evaluation set is designed, not sampled.** It was written by an AI
assistant to a fixed design, with labels that follow from the design; no
human labelled it, and it is not a sample of real agent traffic. See
[`eval/DATASET.md`](./eval/DATASET.md).

**Earlier figures.** Versions of this README up to 0.1.1 reported
AUC = 0.332 on a 60-pair set, r = 0.934, and a median status age of 33.8
hours on real transcripts. Those came from an August 2026 review whose data
and scripts were not kept, so they cannot be re-run. The 0.332 figure is
consistent with a set weighted toward the last row of the table above.

Do not use WARDEN's tag as a signal of whether an agent is on task.

---

## Changes in 0.2.0 (November 2026)

The matcher is unchanged. Everything else below is fixed.

- **Evaluation.** A committed labelled set, an analysis plan written before
  scoring, a `warden eval` command, and a frozen baseline re-checked in CI.
  Full results: [`eval/RESULTS.md`](./eval/RESULTS.md).
- **Stale status.** Tagged `STALE` and not scored.
- **Wrong session.** A mistyped session id resolves to nothing. It no longer
  falls back to the newest Codex transcript or the first partial match.
- **Provenance.** Only the agent's own messages are read for
  `WARDEN_STATUS`; text typed by the user or returned by a tool is ignored.
  Each audit record names the transcript it was read from.
- **Codex.** Current Codex rollout files (message under `payload`) are read.
  Compressed `.jsonl.zst` rollouts are not.
- **Registry.** Survives unknown fields and unreadable records, is written
  atomically, and is updated under a lock, so a session registered while the
  daemon is running is no longer lost.
- **Daemon.** One failing session no longer stops monitoring of the rest.
- **Terminal safety.** Control characters are stripped from status text.
- **Audit trail.** Each record says whether it differs from the previous
  poll; `warden audit --changes-only` hides the repeats.

---

## Install

```bash
cd warden
pip install -e .
```

Requires Python 3.10+ and `click`.

---

## Quick Start

### 1. Inject the rule into the agent

```bash
warden rule
```

Copy the `[WARDEN_RULE]` block into the agent's system prompt / context / CLAUDE.md / AGENTS.md so it periodically emits:

```
WARDEN_STATUS: Setting up FastAPI routes for /score and /debug endpoints
```

### 2. Register a session

`warden watch` registers a session and objective, then exits — it does not
block by default:

```bash
# Claude Code (default)
warden watch \
  --agent claude-code \
  --session abc123 \
  --objective "Build API wrapper for IntentGraph with /score and /debug endpoints"

# Codex
warden watch \
  --agent codex \
  --session my-codex-run \
  --objective "Refactor auth middleware" \
  --transcript ~/.codex/sessions/2026/08/15/rollout-xyz.jsonl
```

`watch` flags:

| Flag | Behavior |
|------|----------|
| *(none)* | Register and exit immediately. This is the default. |
| `--once` | Register, run a single check, print the result, and exit. |
| `--follow` | Register, then block in this terminal, polling this one session on its `--interval` until Ctrl-C. |
| `--background` | Deprecated — identical to the default now. Prints a one-time note pointing at `warden daemon`. |

### 3. Start the daemon

Registering sessions doesn't watch them by itself — start the daemon in a
terminal (or under `nohup`/a service manager) to actually check them:

```bash
warden watch --session abc123 --objective "..."
warden watch --session my-codex-run --objective "..." --agent codex

warden daemon                 # checks every active session on its own --interval
warden daemon --tick 15       # scan every 15s for sessions that are due
```

The daemon reloads the session registry on every tick, so sessions
registered from another terminal are picked up automatically — no restart
needed. Each session is only re-checked once its own `--interval` has
elapsed, so a session polled every 10 minutes and one polled every hour
don't get checked in lockstep.

### 4. Check status

```bash
warden status          # all registered sessions
warden check           # one-shot poll of all active sessions
warden check --session abc123
warden drifts --today
warden drifts --tag DIVERGENT     # cases the two raters disagreed on — needs a human
warden audit --session abc123 --since "1 hour ago"
warden audit --session abc123 --changes-only   # hide polls that repeat the last one
```

### 5. Stop

```bash
warden stop --session abc123
```

---

## How Polling Works

| Agent        | Strategy        | How it finds status                                      |
|--------------|-----------------|----------------------------------------------------------|
| Claude Code  | File watcher    | `~/.claude/projects/<project>/<session>.jsonl`           |
| Codex        | File watcher    | `~/.codex/sessions/**/rollout-*.jsonl`                    |
| Any          | Manual          | You paste the status line when prompted                  |
| Subprocess   | Stdout scrape   | Captures stdout of a process you attach                  |

You can always pass `--transcript /path/to/file` to point at a specific log.

---

## Matching (v1.1 — dual-rater)

Two raters each vote MATCH / UNCLEAR / DRIFT, and WARDEN only commits to a
tag when they agree. **They are not statistically independent** — see
[Known Issues / Limitations](#known-issues--limitations) — so treat
agreement as agreement, not corroboration:

- **Rater A — word overlap.** Jaccard similarity over stemmed keywords, with
  camelCase/PascalCase compounds split before comparison (`FastAPI` → `fast` + `api`)
  so acronym-bearing tech terms overlap correctly with their expansions.
  - `≥ 0.35` → MATCH · `≥ 0.15` → UNCLEAR · below → DRIFT
- **Rater B — character trigrams.** Jaccard similarity over 3-character
  substrings of the raw text. Correlates with Rater A at Pearson r = 0.951 —
  a related measurement of the same underlying overlap, not an independent
  check.
  - `≥ 0.30` → MATCH · `≥ 0.12` → UNCLEAR · below → DRIFT

When the two raters land on the same tag, that tag is logged. When they
disagree, WARDEN logs **`DIVERGENT`** instead of picking a side. Given how
correlated the raters are, most `DIVERGENT` calls are two thresholds
splitting the same underlying score, not two independent assessments in
real disagreement — treat it as a weak signal, not a reliable one. Both
raters' scores are always written to the audit record
(`word_tag`/`word_score`/`trigram_tag`/`trigram_score`) so a divergent call
can be inspected after the fact.

This is intentionally crude and dependency-free. An embedding upgrade path is documented in the design spec for when false positives become annoying.

---

## Status Freshness (STALE)

Before scoring, WARDEN checks how old the status line is. A status older
than `--stale-after` (default 1800s — three missed 10-minute emissions) is
tagged **`STALE`**, logged, and **not scored**.

| Evidence | Result |
|----------|--------|
| The transcript record carrying the status has its own timestamp | Age is known → `FRESH` or `STALE` |
| No record timestamp, but the file's mtime is older than the limit | Status is at least that old → `STALE` |
| No record timestamp, file recently modified | `UNVERIFIED` — scored, and the audit note says the age could not be verified |

A file's mtime can prove a status is old; it cannot prove one is fresh,
because an active transcript can still contain an hours-old status line.

```bash
warden watch --session abc123 --objective "..." --stale-after 900
warden drifts --tag STALE
```

Every audit record carries `freshness`, `status_age_seconds`,
`status_min_age_seconds`, `status_time`, `freshness_basis` and
`stale_after_seconds`. A `STALE` record has no rater scores.

---

## Reproducing the Matcher Evaluation

```bash
warden eval eval/labelled_pairs.jsonl
warden eval eval/labelled_pairs.jsonl --json > eval/baseline.json
```

`warden eval` scores both raters against a labelled JSONL file and reports
AUC with a 95% bootstrap interval that resamples whole objectives (fixed
seed), AUC for each kind of status, the best accuracy at any threshold
against the always-MATCH baseline, the Pearson correlation between the two
raters, and the final tag by kind. The report
includes the SHA-256 of the data file. See [eval/README.md](./eval/README.md)
for the file format.

`tests/test_known_flaw.py` pins the disclosed scoring flaw as strict
expected-failures: CI stays green while the flaw exists and goes red the
moment it is fixed, until the marker and this README are updated.

---

## Data Layout

```
.warden/
  objectives/          # one .objective file per session
  audit/               # YYYY-MM-DD.ndjson
  sessions.json        # registry of watched sessions
  sessions.lock        # lock held while the registry is updated
```

Audit records are newline-delimited JSON:

```json
{
  "timestamp": "2026-08-15T09:14:00+05:30",
  "agent_id": "claude-code-abc123",
  "objective": "Build API wrapper for IntentGraph",
  "status": "Setting up FastAPI routes for /score and /debug endpoints",
  "tag": "MATCH",
  "note": "Status aligns with objective (score=0.36). On track.",
  "action": "NONE",
  "word_tag": "MATCH",
  "word_score": 0.36,
  "trigram_tag": "MATCH",
  "trigram_score": 0.41,
  "freshness": "FRESH",
  "status_age_seconds": 212.0,
  "status_min_age_seconds": null,
  "status_time": "2026-08-15T09:10:28+05:30",
  "freshness_basis": "record-timestamp",
  "stale_after_seconds": 1800,
  "transcript": "/home/me/.claude/projects/intentgraph/abc123.jsonl",
  "changed": true
}
```

---

## Design Notes

- Agent self-reports → ~10 tokens per check instead of reading full history
- No enforcement → user decides what to do with drift notes
- False drift is expected when *you* redirect the agent; the note is awareness, not an alarm
- Pluggable strategies make it straightforward to add Cursor, Grok, Kimi, etc.

---

## Status

- Design: prototype (v0.2.0) — on hold; core detector unchanged and not trustworthy, see [Known Issues / Limitations](#known-issues--limitations)
- Implementation: working CLI + multi-session daemon + Claude Code / Codex file watchers + audit trail; dual-rater matcher runs, but its scoring is not trustworthy (see Known Issues)
- Tests: matcher, audit, polling, freshness, registry, daemon and the evaluation harness. The scoring flaw itself is pinned by strict expected-failure tests and a frozen baseline, so it cannot change unnoticed

Built to be small, honest, and useful. Right now it's small and honest about its own flaw; not yet useful for its stated purpose.

## License
Licensed under PolyForm Noncommercial 1.0.0 — free to use, including
personal and research use. Commercial use requires a separate license.
See [LICENSE](./LICENSE) for full terms, or reach out to discuss
commercial licensing.
