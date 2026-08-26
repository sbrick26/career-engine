# The writing method

Ranking picks *which* facts make the page ([ranking.md](ranking.md)); this doc
is how they become a resume a human actually wants to read. The full rules live
in the resume-writer's charter; this is the shape of them.

## Honesty contract

Every claim traces to a fact row in the hub. Numbers carry a basis - direct, or
estimated with the estimation stated. Titles are real titles. Client names are
generalized at write time ("a national freight carrier"), enforced by a leak-scan
in the consuming site's CI that is hardened daily from a private registry.
Public events (a conference, a summit covered by a public post) stay named -
publicity attaches to the event, never to the confidential client list.

## Role narrative first

The 2026-08-25 revision, after the owner rejected a technically-correct draft
that read like a list of ranked facts:

1. **Thesis bullet.** The first bullet of a role states what the owner owns -
   scope and arc in one line. Every other bullet reads as evidence for it.
2. **Themes, not facts.** Facts group into theme bullets (executive voice,
   revenue and adoption, architecture and build, leadership, product), one
   bullet per theme. A motion and the outcome it produced belong in one line.
3. **Identity coverage.** Within a role's first three bullets a reader must
   see all three identities: architect, builder, and executive-conversation
   leader.
4. **Audience span.** Each bullet carries technical depth AND an
   adoption/revenue outcome AND a strategy signal, so it lands with five
   reader types at once: FDE, solution architect, pre-sales engineer, PM, and
   AI deployment strategist.
5. **The owner's voice.** His verbs (built, led, closed, created, set up), his
   phrasing, no consultant gloss. Draft reviews train this (below).

## Bullet mechanics

Verb-first, no pronouns, one idea per bullet, hard length caps enforced by
lint. Each bullet assembles from a 5-slot schema (verb, artifact, mechanism,
scale, outcome) and must state the highest rung its facts support on the
outcome ladder: adoption/purchase > trial/deployment > competitive win >
pipeline generated > measured result > built. Ending a bullet at "built X"
when the hub records an adoption is a construction defect.

## The taste loop

A redraft never ships on the writer's judgment alone. The pipeline sends the
drafted summary and top bullets to the owner with ship/redo buttons; a text
reply becomes a rework round straight back to the writer (capped), and every
verdict - approved, or reworked with the reason - is recorded and injected
into future writer runs as taste history. The style converges on the owner's
actual preferences instead of a template's.

## One artifact out

The writer's only output is `dist/resume-export.json`, validated against
`contracts/resume-export.schema.json`. A deterministic adapter splices it into
the portfolio site and regenerates the one-page PDF; if the page overflows,
the whole refresh reverts rather than shipping a site/PDF mismatch.
