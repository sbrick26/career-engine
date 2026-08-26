#!/usr/bin/env python3
"""rank.py - the resume ranking engine (deterministic core).

Scores every career fact on five normalized sub-scores, weights them per a TARGET
ROLE profile (career-engine/config/roles.json), and selects a one-page set. The math is
fully reproducible and auditable (the dashboard / resume-writer can show WHY a
bullet made the page). Pairwise Elo refinement for the contested middle layers on
top via the ranking-judge agent (rank.py elo-apply), but this file stands alone.

Sub-scores (each 0..1):
  evidence       quality of metrics (direct > estimated > none)
  impact         log-scaled magnitude of the biggest metric, normalized across the corpus
  distinctiveness tag rarity + the archivist's weight as a prior
  scope          leadership / scale signals in the text
  recency        exponential decay by age (current roles score full)

Usage:
  rank.py score   [--role R] [--section S] [--limit N]   ranked facts (table)
  rank.py select  [--role R] [--lines N]                 one-page selection (table)
  rank.py json    [--role R]                              full ranked data as JSON
  rank.py explain <id> [--role R]                         sub-score breakdown for one fact
  rank.py roles                                           list available role profiles
"""
import json
import math
import os
import re
import sqlite3
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("CAREER_DATA_DIR") or os.path.join(ROOT, "..", "career-corpus")
DB = os.path.join(DATA_DIR, "career.db")
ROLES = os.path.join(ROOT, "config", "roles.json")
HALF_LIFE_DAYS = 540.0
SCOPE_KW = ("led", "lead", "manage", "owned", "ownership", "architect", "cross-team",
            "cross team", "scaled", "mentor", "team of", "end-to-end", "from scratch",
            "founded", "spearhead", "drove", "first", "built the")


BOOSTS = os.path.join(DATA_DIR, "owner-boosts.json")


def load_roles():
    try:
        return json.load(open(ROLES)).get("roles", {})
    except Exception:
        return {}


def load_boosts():
    # owner's explicit "this fact is strong" signal: {fact_id: boost 0..0.3}.
    # Private (career-corpus). This is the owner's judgment overriding pure math.
    try:
        return json.load(open(BOOSTS))
    except Exception:
        return {}


def save_boost(fid, amount):
    b = load_boosts()
    b[str(fid)] = max(0.0, min(0.3, float(amount)))
    json.dump(b, open(BOOSTS, "w"), indent=2)
    return b[str(fid)]


def role_profile(name):
    roles = load_roles()
    r = roles.get(name) or roles.get("default") or {}
    w = r.get("weights", {})
    # fill any missing dimension so weights always cover all five
    for d in ("evidence", "impact", "distinctiveness", "scope", "recency"):
        w.setdefault(d, 0.2)
    r["weights"] = w
    r.setdefault("keywords", [])
    r.setdefault("label", name)
    return r


def parse_value(v):
    """Best-effort numeric magnitude from a metric value like '2M', '40%', '$10k', '3x'."""
    s = str(v).strip().lower().replace(",", "").replace("$", "").replace("+", "")
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    if not m:
        return None
    n = float(m.group(1))
    if "k" in s:
        n *= 1e3
    elif "m" in s and "%" not in s:
        n *= 1e6
    elif "b" in s:
        n *= 1e9
    return n


def parse_metrics(blob):
    try:
        arr = json.loads(blob) if blob else []
        return arr if isinstance(arr, list) else []
    except Exception:
        return []


def load_facts():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id,type,title,detail,action,impact,metrics,tags,priority,resume_section,"
        "in_resume,status,weight,created,updated FROM facts"
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def age_days(row):
    ts = (row.get("updated") or row.get("created") or "")[:19]
    try:
        return max(0.0, (datetime.now() - datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")).days)
    except Exception:
        return 365.0


def subscores(facts):
    # corpus-wide normalizers
    max_weight = max((f.get("weight") or 0) for f in facts) or 1
    # tag frequency for distinctiveness (rarer tags = more distinctive)
    tag_count, n = {}, len(facts) or 1
    for f in facts:
        for t in (json.loads(f["tags"]) if f.get("tags") else []):
            tag_count[str(t).lower()] = tag_count.get(str(t).lower(), 0) + 1
    # impact magnitudes (log-scaled), normalized across the corpus
    raw_impact = {}
    for f in facts:
        best = 0.0
        for mt in parse_metrics(f.get("metrics")):
            val = parse_value(mt.get("value")) if isinstance(mt, dict) else None
            if val and val > 0:
                lv = math.log10(val + 1)
                if mt.get("basis") == "estimated":
                    lv *= 0.8
                best = max(best, lv)
        raw_impact[f["id"]] = best
    max_log = max(raw_impact.values()) or 1.0

    # Qualitative outcome ladder (2026-08-25 fix): evidence and impact used to
    # derive ONLY from numeric metrics, which structurally buried the facts a
    # forward-deployed story runs on - closed deals, GA ships, official
    # adoption, competition wins, public keynotes. Those are verifiable
    # outcomes with real magnitude even when no number is attached. Numeric
    # metrics still dominate when present (max of both paths).
    OUTCOME_TIERS = (
        (0.85, ("closed a", "closed deal", "deal closed", "won 1st", "first place",
                "1st place", "official internal", "official release", "to ga",
                "shipped to ga", " ga)", "ga milestone", "officially adopted",
                "being adopted", "adopted as an official")),
        (0.6,  ("main speaker", "keynote", "executive summit", "public post",
                "publicly", "press", "conference talk", "invited talk")),
        (0.35, ("pilot", "poc delivered", "demo delivered", "in production",
                "deployed to production", "live demo")),
    )
    def outcome_tier(f):
        text = " ".join(str(f.get(k) or "") for k in ("title", "detail", "action", "impact")).lower()
        for score, marks in OUTCOME_TIERS:
            if any(m in text for m in marks):
                return score
        return 0.0

    out = {}
    for f in facts:
        fid = f["id"]
        mets = parse_metrics(f.get("metrics"))
        tier = outcome_tier(f)
        # evidence: direct metric > any metric value > bare metric > outcome
        # markers (a closed deal or GA ship IS evidence) > nothing
        if any(isinstance(m, dict) and m.get("basis") == "direct" for m in mets):
            ev = 1.0
        elif any(isinstance(m, dict) and m.get("value") for m in mets):
            ev = 0.6
        elif mets:
            ev = 0.5
        else:
            ev = 0.15
        if tier >= 0.6:
            ev = max(ev, 0.8)
        elif tier > 0:
            ev = max(ev, 0.5)
        ev = min(1.0, ev + 0.05 * max(0, len(mets) - 1))
        # impact: numeric magnitude, floored by the outcome ladder
        imp = raw_impact[fid] / max_log if max_log else 0.2
        if not mets:
            imp = min(imp, 0.2)
        imp = max(imp, tier)
        # distinctiveness: tag rarity + archivist weight prior
        tags = [t.lower() for t in (json.loads(f["tags"]) if f.get("tags") else [])]
        rarity = sum(1.0 - (tag_count.get(t, 1) / n) for t in tags) / len(tags) if tags else 0.4
        wprior = (f.get("weight") or 0) / max_weight
        dist = 0.5 * rarity + 0.5 * wprior
        # scope
        text = " ".join(str(f.get(k) or "") for k in ("action", "detail", "impact", "title")).lower()
        hits = sum(1 for kw in SCOPE_KW if kw in text)
        scope = min(1.0, hits / 3.0)
        # recency
        if (f.get("status") or "") == "current":
            rec = 1.0
        else:
            rec = max(0.0, min(1.0, 0.5 ** (age_days(f) / HALF_LIFE_DAYS)))
        out[fid] = {"evidence": round(ev, 3), "impact": round(imp, 3),
                    "distinctiveness": round(dist, 3), "scope": round(scope, 3),
                    "recency": round(rec, 3)}
    return out


def keyword_affinity(f, keywords):
    if not keywords:
        return 0.0
    text = " ".join(str(f.get(k) or "") for k in ("title", "detail", "action", "impact")).lower()
    text += " " + " ".join(json.loads(f["tags"]) if f.get("tags") else []).lower()
    hits = sum(1 for kw in keywords if kw.lower() in text)
    return min(1.0, hits / max(4, len(keywords) * 0.4))


def rank(role_name):
    facts = load_facts()
    if not facts:
        return [], role_profile(role_name)
    role = role_profile(role_name)
    subs = subscores(facts)
    boosts = load_boosts()
    w = role["weights"]
    for f in facts:
        s = subs[f["id"]]
        base = sum(w[d] * s[d] for d in w)
        aff = keyword_affinity(f, role["keywords"])
        b = float(boosts.get(str(f["id"]), 0) or 0)
        f["sub"] = s
        f["affinity"] = round(aff, 3)
        f["boost"] = round(b, 3)
        f["composite"] = round(base + 0.10 * aff + b, 4)
    facts.sort(key=lambda x: x["composite"], reverse=True)
    return facts, role


def est_lines(f):
    return 2 if (f.get("metrics") and f["metrics"] not in ("", "[]")) or len(f.get("detail") or "") > 120 else 1


def select(role_name, budget_lines=34):
    facts, role = rank(role_name)
    # knapsack-lite: greedy by composite, capped per section, within a line budget
    section_cap = {"summary": 4, "experience": 12, "projects": 12, "skills": 6, "education": 3}
    used, used_sec, chosen = 0, {}, []
    for f in facts:
        sec = f.get("resume_section") or ("projects" if f["type"] == "project" else "experience")
        if used_sec.get(sec, 0) >= section_cap.get(sec, 8):
            continue
        ln = est_lines(f)
        if used + ln > budget_lines:
            continue
        chosen.append(f)
        used += ln
        used_sec[sec] = used_sec.get(sec, 0) + 1
    return chosen, facts, role


# ---- pairwise Elo refinement (the contested middle) --------------------------
def contested(facts, top=6, window=18):
    # the facts whose ORDER matters most: just inside and around the page cut line
    return facts[top:top + window]


def make_pairs(facts, top=6, window=18, span=3):
    """Adjacent + near pairs over the contested set (a sliding window), so the
    judge does O(n) comparisons, not O(n^2)."""
    pool = contested(facts, top, window)
    pairs = []
    for i in range(len(pool)):
        for j in range(i + 1, min(i + 1 + span, len(pool))):
            a, b = pool[i], pool[j]
            pairs.append({"a": a["id"], "b": b["id"], "a_title": a["title"], "b_title": b["title"]})
    return pairs


def elo_scores(ids, comparisons, k=24, iters=4):
    r = {i: 1500.0 for i in ids}
    for _ in range(iters):
        for c in comparisons:
            w, l = c.get("winner"), c.get("loser")
            if w not in r or l not in r or w == l:
                continue
            ew = 1.0 / (1.0 + 10 ** ((r[l] - r[w]) / 400.0))
            r[w] += k * (1.0 - ew)
            r[l] -= k * (1.0 - ew)
    return r


def refine(role_name, comparisons, elo_nudge=0.12):
    """Refine the order with pairwise judgments WITHOUT breaking the score scale:
    a judged fact stays anchored to its composite and is nudged up/down by its
    Elo (max +/- elo_nudge/2). So head-to-head wins reorder close contests but a
    fact never leapfrogs a far-stronger one it was never compared against."""
    facts, role = rank(role_name)
    judged = {c["winner"] for c in comparisons} | {c["loser"] for c in comparisons}
    if judged:
        elo = elo_scores(list(judged), comparisons)
        lo, hi = min(elo.values()), max(elo.values())
        rng = (hi - lo) or 1.0
        for f in facts:
            if f["id"] in elo:
                enorm = (elo[f["id"]] - lo) / rng           # 0..1 within the judged set
                f["refined"] = round(f["composite"] + elo_nudge * (enorm - 0.5), 4)
                f["elo"] = round(elo[f["id"]], 1)
            else:
                f["refined"] = None
    facts.sort(key=lambda x: (x.get("refined") if x.get("refined") is not None else x["composite"]), reverse=True)
    return facts, role


def _row(f):
    return f"{f['id']:>3}  {f['composite']:.3f}  {(f.get('resume_section') or f['type'])[:10]:<10}  {f['title'][:60]}"


def main(argv):
    cmd = argv[0] if argv else "score"
    role = "default"
    if "--role" in argv:
        role = argv[argv.index("--role") + 1]

    if cmd == "roles":
        for k, v in load_roles().items():
            print(f"{k:<14} {v.get('label', '')}")
        return 0
    if cmd == "score":
        facts, r = rank(role)
        limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else 20
        sec = argv[argv.index("--section") + 1] if "--section" in argv else None
        print(f"# ranked for role '{role}' ({r['label']})  -  id  score  section  title")
        shown = [f for f in facts if (not sec or f.get("resume_section") == sec)][:limit]
        for f in shown:
            print(_row(f))
        return 0
    if cmd == "select":
        lines = int(argv[argv.index("--lines") + 1]) if "--lines" in argv else 34
        chosen, _, r = select(role, lines)
        print(f"# one-page selection for '{role}' ({r['label']})  -  {len(chosen)} facts, ~{sum(est_lines(f) for f in chosen)} lines")
        for f in chosen:
            print(_row(f))
        return 0
    if cmd == "json":
        facts, r = rank(role)
        print(json.dumps({"role": role, "label": r["label"],
                          "facts": [{"id": f["id"], "title": f["title"], "type": f["type"],
                                     "section": f.get("resume_section"), "composite": f["composite"],
                                     "sub": f["sub"], "affinity": f["affinity"]} for f in facts]}))
        return 0
    if cmd == "explain":
        fid = int(argv[1])
        facts, r = rank(role)
        f = next((x for x in facts if x["id"] == fid), None)
        if not f:
            print("no such fact"); return 1
        print(f"fact {fid}: {f['title']}")
        print(f"role '{role}' weights: {r['weights']}")
        for d, val in f["sub"].items():
            print(f"  {d:<15} {val:.3f}  x {r['weights'][d]:.2f} = {val * r['weights'][d]:.3f}")
        print(f"  affinity        {f['affinity']:.3f}  x 0.10 = {f['affinity'] * 0.10:.3f}")
        if f.get("boost"):
            print(f"  owner-boost     +{f['boost']:.3f}  (you marked this fact strong)")
        print(f"  COMPOSITE = {f['composite']:.4f}")
        return 0
    if cmd == "boost":
        fid = int(argv[1]); amt = float(argv[2]) if len(argv) > 2 else 0.15
        print(f"owner-boost set: fact {fid} += {save_boost(fid, amt)}")
        return 0
    if cmd == "pairs":
        facts, _ = rank(role)
        print(json.dumps(make_pairs(facts)))
        return 0
    if cmd == "refine":
        comps = json.load(open(argv[1]))
        facts, _ = refine(role, comps)
        print(f"# refined (composite + pairwise Elo) for role '{role}'")
        for f in facts[:20]:
            print(_row(f) + (f"  elo={f['elo']}" if f.get("elo") else ""))
        return 0
    sys.stderr.write(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
