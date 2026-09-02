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


FILE_TOOLS = {"Read", "Edit", "Write", "NotebookEdit", "MultiEdit"}


def files_touched(row):
    """Paths the agent actually opened in this row. The tool_use blocks carry them
    verbatim, so a dropped window's file list is recoverable from the transcript."""
    out = []
    for b in blocks(row):
        if not isinstance(b, dict) or b.get("type") != "tool_use":
            continue
        if b.get("name") in FILE_TOOLS:
            p = (b.get("input") or {}).get("file_path")
            if isinstance(p, str) and p:
                out.append(p)
    return out


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
        files = []
        for r in w:
            for p in files_touched(r):
                if p not in files:
                    files.append(p)
        windows.append({"rows": len(w), "tokens_in": tokens_in, "tokens_out": tokens_out,
                        "user_in": user, "tool_in": tool, "assistant_in": asst,
                        "files": files})
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
    dropped = []
    for w in windows:
        for p in w["files"]:
            if p not in dropped:
                dropped.append(p)
    if dropped:
        print(f"\nfiles the agent read and no longer has ({len(dropped)}):")
        for p in dropped[:25]:
            print("   " + p)
        if len(dropped) > 25:
            print(f"   ... and {len(dropped) - 25} more (--files for all)")
    print("\nif 'kept' sits under 1%, everything the agent read is gone. Ask it about any")
    print("file above and it answers from the summary, without saying so.")


def latest_dir():
    base = os.path.expanduser("~/.claude/projects")
    if not os.path.isdir(base):
        sys.exit("no ~/.claude/projects directory found; has Claude Code run on this machine?")
    dirs = [os.path.join(base, d) for d in os.listdir(base)
            if os.path.isdir(os.path.join(base, d))]
    if not dirs:
        sys.exit("no project directories under ~/.claude/projects")
    # Rank by the newest TRANSCRIPT, never by the directory's own mtime. A
    # directory's mtime only moves when an entry is added or removed, so a
    # project whose transcripts are appended to in place looks stale and
    # --latest silently audits the wrong project, reporting "no compactions"
    # on a session that compacted. Measured 2026-08-31: four of the top five
    # projects on this machine had a directory mtime lagging their newest
    # transcript, one by three and a half months.
    def newest_transcript(d):
        stamps = [os.path.getmtime(f) for f in glob.glob(os.path.join(d, "*.jsonl"))]
        return max(stamps) if stamps else os.path.getmtime(d)
    return max(dirs, key=newest_transcript)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("path", nargs="?", help="a transcript .jsonl, or a directory of them")
    p.add_argument("--latest", action="store_true", help="audit the most recently active project")
    p.add_argument("--self-test", action="store_true", help="run against the bundled fixtures")
    p.add_argument("--only", type=int, metavar="N", help="report a single compaction window in detail")
    p.add_argument("--json", action="store_true", help="machine-readable output, for CI or tracking kept%% over time")
    p.add_argument("--min-kept", type=float, metavar="PCT",
                   help="exit 1 if any window kept less than PCT%% of its tokens "
                        "(use in CI; --json alone always exits 0)")
    p.add_argument("--files", action="store_true", help="print every dropped file path, unabridged")
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
    worst = None
    if a.json:
        out = {os.path.basename(f): audit(rows_of(f)) for f in files}
        for windows in out.values():
            for w in windows:
                w["kept_pct"] = round(100.0 * w["tokens_out"] / w["tokens_in"], 4) if w["tokens_in"] else 0.0
                worst = w["kept_pct"] if worst is None else min(worst, w["kept_pct"])
        print(json.dumps(out, indent=1))
        if a.min_kept is not None and worst is not None and worst < a.min_kept:
            sys.stderr.write(f"kept {worst}% in the worst window, under the {a.min_kept}% floor\n")
            sys.exit(1)
        return
    if a.min_kept is not None:
        sys.exit("--min-kept only applies with --json")
    found = False
    for f in files:
        w = audit(rows_of(f))
        if not w:
            continue
        found = True
        if a.files:
            seen = []
            for x in w:
                for p in x["files"]:
                    if p not in seen:
                        seen.append(p)
            print(f"{os.path.basename(f)}  {len(seen)} file(s) read and dropped")
            for p in seen:
                print("  " + p)
        elif a.only:
            if not 1 <= a.only <= len(w):
                sys.exit(f"{os.path.basename(f)}: has {len(w)} compaction(s), no window {a.only}")
            x = w[a.only - 1]
            comp = x["user_in"] + x["tool_in"] + x["assistant_in"]
            print(f"{os.path.basename(f)}  window {a.only} of {len(w)}")
            print(f"  rows replaced {x['rows']:,} · tokens in {x['tokens_in']:,} · summary {x['tokens_out']:,} "
                  f"· kept {x['tokens_out']/x['tokens_in']*100 if x['tokens_in'] else 0:.1f}%")
            if comp:
                print(f"  in: tool results {x['tool_in']/comp*100:.1f}% · the agent's turns "
                      f"{x['assistant_in']/comp*100:.1f}% · your messages {x['user_in']/comp*100:.1f}%")
            if x["files"]:
                print(f"  files it read and no longer has ({len(x['files'])}):")
                for p in x["files"]:
                    print("     " + p)
        else:
            report(w, os.path.basename(f))
            print()
    if not found:
        print("no compactions in any transcript here; these sessions never ran out of room.")


if __name__ == "__main__":
    main()
