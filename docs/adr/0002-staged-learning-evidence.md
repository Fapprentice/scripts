# 0002. Separate node, stage, and outcome evidence

## Status

Accepted

## Context

A learning goal needs both diagnostic precision and real-world transfer. Treating every task as a single undifferentiated item creates two failure modes: large tasks cannot attribute failure to a skill, while tiny tasks can report mastery without showing that skills work together. Letting AI freely combine completed nodes also makes prerequisites, acceptance, and progress non-reproducible.

## Decision

Task Verge uses four distinct layers for learning goals:

1. A **Skill** is the smallest independently assessable ability, not the smallest mechanical action.
2. A **Node Task** has exactly one primary skill and may use already-qualified supporting skills. Only the primary skill receives mastery evidence.
3. A **Stage Task** instantiates a versioned Skill Pack stage template. It combines 2–4 qualified required skills in one coherent transfer context and produces integration evidence.
4. An **Outcome Task** directly verifies the goal contract and its success criteria. Passing stages never completes the goal by itself.

Skill Packs own legal stage combinations, required/optional/forbidden skills, integration behavior, outcome shape, and per-skill observation points. AI may instantiate scenarios, materials, hints, and bounded difficulty, but may not remove required skills, introduce an unqualified required skill, lower evidence contracts, or change hard prerequisites.

Stage failure does not revoke all node mastery. Deterministic observation points attribute failures first; semantic evaluation handles unresolved evidence; remaining uncertainty becomes needs_review. Stage success creates one integration event and does not multiply companion growth by the number of skills.

Map coverage repair is an internal system/AI planning action and is never dispatched as a user task.

## Consequences

- Node mastery evidence, integration evidence, and goal evidence are stored and settled separately.
- Task generation and acceptance must understand node, stage, and outcome task kinds.
- Stage eligibility requires satisfied node contracts, no due required skill, no unmet hard prerequisite, a valid pack/version template, complete materials, and enough time for the minimum viable scenario.
- Final-outcome eligibility is based on required criterion coverage, required skills, required integration gates, and hard prerequisites—not all nodes or all optional stages.
- Existing tasks migrate as node tasks when they have one skill; ambiguous multi-skill tasks remain legacy tasks and cannot create integration evidence retroactively.
