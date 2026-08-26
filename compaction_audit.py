#!/usr/bin/env python3
"""compaction_audit.py: what did Claude Code's compaction keep, and whose words were they?

Reads the transcript files Claude Code already writes to ~/.claude/projects/<project>/*.jsonl,
finds every compaction (the summary rows flagged isCompactSummary), and prints what each one
replaced: tokens in, summary tokens out, the share kept, and the composition of what went in.

Everything runs locally and prints aggregates only. Nothing leaves your machine.
Token counts are estimated at 4 characters per token, the same arithmetic used in
"Claude Code vs Codex CLI vs Cursor in 2026" (The AI Engineer).
"""
import argparse
import glob
import json
import os
import sys


def rows_of(path):
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass                       # a torn line must not kill the audit
    return out


def text_of(row):
    msg = row.get("message") or {}
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = []
        for b in c:
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            if t == "text":
                parts.append(b.get("text", ""))
            elif t == "tool_use":
                parts.append(json.dumps(b.get("input", {})))
            elif t == "tool_result":
                parts.append(json.dumps(b.get("content"))[:100000])
        return " ".join(parts)
    return ""


def blocks(row):
    c = (row.get("message") or {}).get("content")
    return c if isinstance(c, list) else []


def audit(rows):
    """One dict per compaction window. Windows run from the last compaction (or the
    session start) to the next isCompactSummary row, which replaces them."""
    marks = [i for i, r in enumerate(rows) if r.get("isCompactSummary")]
    windows, prev = [], 0
    for i in marks:
        w = rows[prev:i]
        tokens_in = sum(len(text_of(r)) for r in w
                        if r.get("type") in ("user", "assistant")) // 4
        tokens_out = len(text_of(rows[i])) // 4
        user = tool = asst = 0
        for r in w:
            if r.get("type") == "user":
                bs = blocks(r)
                if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in bs):
                    tool += len(json.dumps(bs)) // 4
                else:
                    user += len(text_of(r)) // 4
            elif r.get("type") == "assistant":
                asst += len(json.dumps(blocks(r))) // 4
        windows.append({"rows": len(w), "tokens_in": tokens_in, "tokens_out": tokens_out,
                        "user_in": user, "tool_in": tool, "assistant_in": asst})
        prev = i
    return windows


def report(windows, label):
    if not windows:
        print(f"{label}: no compactions. This session never ran out of room; nothing was thrown away.")
        return
    print(label)
    print(f"{'#':>3} {'rows':>6} {'tokens in':>12} {'summary':>9} {'kept':>7}")
    ti = to = u = t = a = 0
    for n, w in enumerate(windows, 1):
        pct = w["tokens_out"] / w["tokens_in"] * 100 if w["tokens_in"] else 0.0
        print(f"{n:>3} {w['rows']:>6} {w['tokens_in']:>12,} {w['tokens_out']:>9,} {pct:>6.1f}%")
        ti += w["tokens_in"]; to += w["tokens_out"]
        u += w["user_in"]; t += w["tool_in"]; a += w["assistant_in"]
    tot_pct = to / ti * 100 if ti else 0.0
    print(f"{'':>3} {'':>6} {ti:>12,} {to:>9,} {tot_pct:>6.1f}%   <- total")
    comp = u + t + a
    if comp:
        print(f"\nwhat went in:  tool results {t/comp*100:.1f}%  ·  "
              f"the agent's turns {a/comp*100:.1f}%  ·  your messages {u/comp*100:.1f}%")
    print("\nif 'kept' sits under 1%, everything the agent read is gone. Expect it to")
    print("re-read files it already read, without telling you.")


def latest_dir():
    base = os.path.expanduser("~/.claude/projects")
    if not os.path.isdir(base):
        sys.exit("no ~/.claude/projects directory found; has Claude Code run on this machine?")
    dirs = [os.path.join(base, d) for d in os.listdir(base)
            if os.path.isdir(os.path.join(base, d))]
    if not dirs:
        sys.exit("no project directories under ~/.claude/projects")
    return max(dirs, key=os.path.getmtime)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("path", nargs="?", help="a transcript .jsonl, or a directory of them")
    p.add_argument("--latest", action="store_true", help="audit the most recently active project")
    p.add_argument("--self-test", action="store_true", help="run against the bundled fixtures")
    a = p.parse_args()

    if a.self_test:
        here = os.path.dirname(os.path.abspath(__file__))
        got = audit(rows_of(os.path.join(here, "fixtures", "sample.jsonl")))
        with open(os.path.join(here, "fixtures", "expected.json"), encoding="utf-8") as f:
            exp = json.load(f)
        if got != exp:
            print("SELF-TEST FAIL")
            print("expected:", json.dumps(exp))
            print("got:     ", json.dumps(got))
            sys.exit(1)
        report(got, "self-test fixtures")
        print("\nSELF-TEST PASS")
        return

    target = latest_dir() if a.latest else a.path
    if not target:
        p.print_help()
        sys.exit(2)
    files = [target] if os.path.isfile(target) else sorted(glob.glob(os.path.join(target, "*.jsonl")))
    if not files:
        sys.exit(f"no .jsonl files under {target}")
    found = False
    for f in files:
        w = audit(rows_of(f))
        if w:
            found = True
            report(w, os.path.basename(f))
            print()
    if not found:
        print("no compactions in any transcript here; these sessions never ran out of room.")


if __name__ == "__main__":
    main()
