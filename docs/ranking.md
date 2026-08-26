# How the ranking works

`bin/rank.py` decides which facts earn a place on the one-page resume. The math
is deterministic and auditable: `rank.py explain <id>` shows exactly why any
fact ranks where it does.

## Five sub-scores (each 0..1)

| Sub-score | What it measures |
|---|---|
| **evidence** | How verifiable the fact is. A direct metric scores 1.0, an estimated one 0.6. Since 2026-08-25, verifiable *outcomes* count too (see the outcome ladder below) - a closed deal or a shipped GA is evidence even with no number attached. |
| **impact** | Magnitude. Log-scaled size of the fact's biggest metric, normalized across the corpus - floored by the outcome ladder when the outcome is categorical rather than numeric. |
| **distinctiveness** | How unusual the fact is: tag rarity across the corpus, blended with the archivist's editorial weight as a prior. |
| **scope** | Leadership and scale signals in the text (led, owned, architected, founded, team of, end to end). |
| **recency** | Exponential decay with a ~18-month half-life; facts attached to a current role score full. |

## The outcome ladder

The original scorer derived evidence and impact purely from numeric metrics,
which structurally buried exactly the facts a field-engineering story runs on:
a keynote, a closed deal, a GA release, a competition win. None of those need a
number to be real. The ladder fixes that with deterministic text markers:

| Tier | Markers (examples) | Effect |
|---|---|---|
| 0.85 | closed a deal, won 1st place, adopted as official, shipped to GA | evidence floored at 0.8, impact floored at 0.85 |
| 0.60 | main speaker, keynote, executive summit, public post | evidence floored at 0.8, impact floored at 0.60 |
| 0.35 | pilot, live demo, deployed to production | evidence floored at 0.5, impact floored at 0.35 |

Numeric metrics still dominate when present - the ladder is a floor, not a cap.

## Role profiles

The same corpus ranks differently per target role. Each profile in
`config/roles.json` re-weights the five sub-scores and lists keywords that earn
an affinity bonus (up to +0.10 on the composite). Current profiles:

- **fde** (default target): AI forward deployed engineer - scope and
  distinctiveness weighted up; affinity for executive, closed, adoption,
  architecture, governance, modernization.
- **sa-presales**: solution architect / pre-sales engineer.
- **ai-strategist**: AI deployment strategist / PM - adoption, governance,
  enablement, ROI.
- **default** / **ai-engineer**: generic software / AI engineering cuts.

## Composite and selection

```
composite = sum(role_weight[d] * subscore[d]) + 0.10 * keyword_affinity + owner_boost
```

`owner_boost` is the owner's explicit thumb on the scale (0..0.3 per fact,
stored outside the repo). Selection is a greedy knapsack over an estimated
34-line page budget with per-section caps, so a strong section can never crowd
the whole page.

## Elo refinement

The contested middle - the facts just inside and just outside the page cut -
is where ordering matters most and pure arithmetic is least trustworthy. A
ranking-judge agent runs pairwise comparisons over that window and
`rank.py elo-apply` folds the results back in. The deterministic core stands
alone; the judge only refines the boundary.

## What keeps it honest

Rankings only order facts; they never create them. Every fact comes from the
archivist's interviews with provenance, numbers carry a basis (direct or
estimated), and facts missing a number generate follow-up questions for the
owner instead of invented figures. See [writing-method.md](writing-method.md)
for what happens after selection.
