# Glimi Skills

Persona/manager behavioral skills. Each skill is a `SKILL.md` file with frontmatter + body, in **English** as the canonical source. Locale-specific phrasing examples live in `_examples/<skill>.<lang>.md`.

## Format

```markdown
---
name: <unique-key>
description: <one-line summary>
applies-to: persona | mgr | creator | all
when-to-use: <trigger condition — what prompt segment / situation activates this>
priority: 1-10 (higher = higher injection precedence)
---

<body in English — principles, rules, examples in abstract terms, "Never do" list,
core stance / one-line spirit>

→ Korean phrasing examples: see `_examples/<skill>.ko.md`
```

## Why English canonical?

Per `CLAUDE.md`: prompt source is English; locale-specific phrasing (Korean filler 어휘 / honorifics / 카톡 style etc.) is injected via `src/core/prompts/locale.py` helpers or per-language overrides. Skill files follow the same rule — body in English, locale examples separate.

## Skills

| Skill | Applies | Priority | Purpose |
|---|---|---|---|
| `ambient-awareness` | all | 8 | Reference other-channel context naturally |
| `conversation-join` | persona | 6 | Enter in-progress group chats |
| `emotional-expression` | persona | 5 | Reflect current emotion in tone |
| `memory-recall` | all | 3 | Reference memory section without reciting |
| `meta-question-handling` | persona | 2 | Handle "are you AI?" type questions |

## Adding a new skill

1. Create `skills/<key>/SKILL.md` following the format above
2. Add Korean (or other) examples to `_examples/<key>.ko.md` if needed
3. Update this README's table

## Examples directory (`_examples/`)

Hosts locale-specific phrasing examples that would clutter the canonical English skill body. Underscore prefix excludes from skill discovery (consistent with the achievements catalog `_shared.py` pattern).
