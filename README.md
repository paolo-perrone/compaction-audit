# compaction-audit

> **Status:** run end to end. The self-test is green in CI, the audit reproduced the
> issue's measurement on the session that produced it, and the fresh-clone path is
> verified on stock `python3`.

Companion to [Claude Code vs Codex CLI vs Cursor in 2026](https://theaiengineer.substack.com/p/claude-code-vs-codex-cli-vs-cursor-in-2026).

When Claude Code runs out of room it compacts: the conversation so far is replaced with a
written summary and the rest is dropped. No vendor documents what survives. This prints it,
from the transcript files already sitting on your machine.

## Run it

```bash
git clone https://github.com/paoloap-py/compaction-audit.git
cd compaction-audit
python3 compaction_audit.py --self-test
```

The self-test runs the audit against bundled fixtures with known numbers and exits non-zero
on any mismatch. Then point it at your own most recently active project:

```bash
python3 compaction_audit.py --latest
```

Or at one transcript, or a whole project directory:

```bash
python3 compaction_audit.py ~/.claude/projects/<project>/<session>.jsonl
```

Every dropped file path, one compaction at a time, or machine-readable for CI:

```bash
python3 compaction_audit.py --latest --files
python3 compaction_audit.py --latest --only 3
python3 compaction_audit.py --latest --json
```

Standard library only, Python 3.9+, no install. It reads locally and prints aggregates.
Nothing leaves your machine.

## What it reports

One line per compaction: the rows it replaced, estimated tokens in, summary tokens out, and
the share kept. Then the composition of what went in: tool results against the agent's own
turns against your typed messages. Then the file paths themselves, every source file the
agent opened inside the dropped windows and no longer holds.

On the session that produced the issue it reports six compactions, 4,820,699 tokens of
conversation replaced by 26,593 tokens of summary, 0.6% kept, and 158 files the agent read
and no longer has. Tool results were 50.7% of
what went in; the author's typed messages were 5.7% of what went in and 29% of what came
out. Compaction keeps what you asked at roughly five times the rate it keeps what the
agent read.

## How it counts

A token is estimated as 4 characters, the standard rough cut. Window boundaries are the
`isCompactSummary` rows Claude Code writes into the transcript; each window runs from the
previous compaction (or the session start) to the summary that replaced it. File paths come
from the `file_path` argument on `Read`, `Edit`, `Write`, `MultiEdit` and `NotebookEdit`
tool calls, so a file the agent only ran `grep` against will not appear. Only `user` and
`assistant` rows count toward window size, so queue operations and attachments do not
inflate the totals. Torn lines are skipped rather than fatal.

The estimate is deliberately simple. The point is the ratio, and the ratio survives the
4-characters approximation. The composition percentages are measured over the serialized
message blocks, so their total differs slightly from the window token column; both follow
the article's method exactly, which is what makes its numbers reproducible here.

If it reports no compactions for a session you know compacted, Claude Code's transcript
format has changed its `isCompactSummary` flag; open an issue.

## Reading the result

If `kept` sits under 1%, everything the agent read in that window is gone: file contents,
tool output, the evidence behind its conclusions. Ask it about any file on the dropped list
and it answers from the summary, at the same confidence, without saying so.
