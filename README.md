# WARDEN

**Lightweight Agent Drift Detection & Audit System**

Version 0.1.1

Warden is an external observer for long-running AI coding agents (Claude Code, Codex, and others).  
It does **not** control, rewrite, or interrupt the agent.  
It only:

1. Collects a single-line status the agent emits every N minutes  
2. Compares that status to the original objective  
3. Tags it `MATCH` / `DRIFT` / `UNCLEAR`  
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

### 2. Start watching a session

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

# Register only (no blocking loop)
warden watch --session abc123 --objective "..." --background
```

### 3. Check status

```bash
warden status          # all registered sessions
warden check           # one-shot poll of all active sessions
warden check --session abc123
warden drifts --today
warden audit --session abc123 --since "1 hour ago"
```

### 4. Stop

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

## Matching (v1)

Simple keyword overlap (Jaccard) after stop-word removal and light stemming.

- `≥ 0.45` → **MATCH**
- `≥ 0.18` → **UNCLEAR**
- below    → **DRIFT**

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
  "note": "Status aligns with objective (score=0.52). On track.",
  "action": "NONE",
  "score": 0.52
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
- Implementation: working CLI + Claude Code / Codex file watchers + matcher + audit
- Tests: matcher, audit, status extraction

Built to be small, honest, and useful.
