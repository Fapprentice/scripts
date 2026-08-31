# 0001. Skill Map is the plan source for learning goals

## Status

Accepted

## Context

Task Verge already treats the goal contract as immutable and the task plan as adjustable. Learning goals still generated daily tasks first and upserted a knowledge graph afterwards. Mastery was FSRS retrievability, prerequisites were untyped, and diagnostics stopped at coarse ability buckets.

Marble's useful idea is a computable curriculum: nodes with mastery evidence, hard/soft prerequisites with rationales, and generation constrained by that map. Copying a child sandbox would fight this product. Making the skill map the plan source does not.

## Decision

For learning goals, a versioned skill map is the plan source of truth. Today's tasks are taken from unlocked, unmastered, or due nodes. Task acceptance stays in `acceptance.py`. Skill mastery updates only when submitted evidence satisfies the node contract. Companion growth still follows task acceptance, never an inferred mastery bar.

Skill packs (`cet4`, `python-intro`) are hand-written templates. AI may propose additional nodes only through the same validation seam. Cycles reject the proposed graph. Missing edge kind is treated as hard for unlock compatibility and marked `legacy_unspecified` so new generation cannot invent it.

## Consequences

- `learning.py` exposes a small SkillMap interface; `adaptive` and generation call that interface.
- Empty or uncovered maps block ordinary learning-task generation.
- Recall ratings apply only to recall demonstrations.
- Goal success criteria still cannot be lowered by feedback; feedback may only change the route on the map.
