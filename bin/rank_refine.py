#!/usr/bin/env python3
"""rank_refine.py [role] [--max-pairs N] - refine the resume ranking with REAL
pairwise judgments from the ranking-judge agent, then apply the Elo blend.

Pipeline: rank.py pairs (contested middle) -> judge each pair via agentctl
(ranking-judge, structured winner A/B) -> rank.py refine (composite + Elo).
Writes the judgments to career-corpus/rank-comparisons.json. Bounded by
--max-pairs so the number of judge calls is predictable.
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA = {"type": "object",
          "properties": {"winner": {"type": "string", "enum": ["A", "B"]},
                         "reason": {"type": "string"}},
          "required": ["winner", "reason"]}


def sh(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, cwd=ROOT, **kw)


def main():
    argv = sys.argv[1:]
    role = argv[0] if argv and not argv[0].startswith("--") else "default"
    maxp = int(argv[argv.index("--max-pairs") + 1]) if "--max-pairs" in argv else 24
    pairs = json.loads(sh(["python3", "scripts/rank.py", "pairs", "--role", role]).stdout or "[]")[:maxp]
    if not pairs:
        print("no contested pairs to judge"); return 0
    sf = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    sf.write(json.dumps(SCHEMA)); sf.close()
    comps = []
    for i, p in enumerate(pairs, 1):
        # raw (no Task-tool indirection) + self-contained rubric = reliable structured output
        task = ("You are a resume ranking judge. Pick the single STRONGER bullet for a one-page "
                "resume aimed at the target role. Prefer concrete impact (real numbers/scale), "
                "distinctiveness (named systems, hard problems, ownership), relevance to the role, "
                "and recency. Judge substance, not wording. No ties.\n"
                f"Target role: {role}.\nA: {p['a_title']}\nB: {p['b_title']}\n"
                "Return winner exactly A or B with a one-sentence reason.")
        r = sh(["bash", "scripts/agentctl.sh", "run", "ranking-judge", "--raw", "--json-schema", sf.name,
                "--label", f"judge {p['a']} vs {p['b']}", "--task", task])
        win = None
        try:
            win = json.loads(r.stdout.strip()).get("winner")
        except Exception:
            pass
        if win == "A":
            comps.append({"winner": p["a"], "loser": p["b"]})
        elif win == "B":
            comps.append({"winner": p["b"], "loser": p["a"]})
        sys.stderr.write(f"  [{i}/{len(pairs)}] {p['a']} vs {p['b']} -> {win}\n")
    os.unlink(sf.name)
    cf = os.path.join(os.environ.get("CAREER_DATA_DIR") or os.path.join(ROOT, "..", "career-corpus"), "rank-comparisons.json")
    json.dump(comps, open(cf, "w"), indent=2)
    print(f"# {len(comps)} real judgments -> refined ranking (role {role})\n")
    print(sh(["python3", "scripts/rank.py", "refine", cf, "--role", role]).stdout)


if __name__ == "__main__":
    main()
