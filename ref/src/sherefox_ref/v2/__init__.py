"""v2 debate reference model (00_core_rules.md rules 0.5) for the demo chapter
《守靈夜消失的遺囑》 (11_demo_chapter.md). Stdlib only, deterministic.

Modules: data (chapter JSON), model (constants, actions, state), known (claim display),
resolve (resolve_round), policy (opponent), results (grade / truth / reputation),
routes (ch §12 replays), play (seeded full run), trace (golden JSON dumper).
Every place where the design text is silent or contradictory is marked SPEC-QUESTION.
"""
