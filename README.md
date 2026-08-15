# WARDEN

**Lightweight Agent Drift Detection & Audit System**

Version 0.1.1

Warden is an external observer for long-running AI coding agents (Claude Code, Codex, and others).  
It does **not** control, rewrite, or interrupt the agent.  
It only:

1. Collects a single-line status the agent emits every N minutes  
2. Compares that status to the original objective  
3. Tags it `MATCH` / `DRIFT` / `UNCLEAR` / `DIVERGENT`  
4. Writes a short note to an append-only NDJSON audit trail  

---

## Core Principle

> Observe only. Never intervene.

This is the product's identity.

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

Two structurally independent raters each vote MATCH / UNCLEAR / DRIFT, and WARDEN
only commits to a tag when they agree:

- **Rater A — word overlap.** Jaccard similarity over stemmed keywords, with
  camelCase/PascalCase compounds split before comparison (`FastAPI` → `fast` + `api`)
  so acronym-bearing tech terms overlap correctly with their expansions.
  - `≥ 0.35` → MATCH · `≥ 0.15` → UNCLEAR · below → DRIFT
- **Rater B — character trigrams.** Jaccard similarity over 3-character
  substrings of the raw text. Catches morphological overlap word-stemming
  misses, and misses things word-overlap catches — a different failure mode
  by construction.
  - `≥ 0.30` → MATCH · `≥ 0.12` → UNCLEAR · below → DRIFT

When the two raters land on the same tag, that tag is logged. When they
disagree, WARDEN logs **`DIVERGENT`** instead of picking a side — that
disagreement is the signal that needs a human, not an algorithm to break the
tie. Both raters' scores are always written to the audit record
(`word_tag`/`word_score`/`trigram_tag`/`trigram_score`) so a divergent call
can be inspected after the fact.

This is intentionally crude and dependency-free. An embedding upgrade path is documented in the design spec for when false positives become annoying.

---

## Data Layout

```
.warden/
  objectives/          # one .objective file per session
  audit/               # YYYY-MM-DD.ndjson
  sessions.json        # registry of watched sessions
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
  "trigram_score": 0.41
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

- Design: complete (v0.1.1)
- Implementation: working CLI + multi-session daemon + Claude Code / Codex file watchers + dual-rater matcher + audit
- Tests: matcher, audit, status extraction

Built to be small, honest, and useful.
