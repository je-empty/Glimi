# Glimi Skills

Behavioral skills injected into agent system prompts. Each skill is a `SKILL.md`
file with frontmatter + body, in **English** as the canonical source. Locale-specific
phrasing examples live in `_examples/<skill>.<lang>.md`.

## Core ships base behaviors; apps extend them

Skills resolve over a **search path** — kernel base behaviors first, then the
consuming app's domain skills, where the app **overrides core by `name`**:

| Location | Ships | Examples |
|---|---|---|
| `glimi/skills/` (this dir — kernel) | generic agent behaviors | ambient-awareness, conversation-join, emotional-expression, memory-recall |
| `community/skills/` (Community app) | domain policy that can't live in a neutral kernel | meta-question-handling ("you are a human character; never admit AI") |

The loader (`community/core/skills.py → build_skills_section(agent_type)`) scans both
dirs and `community/core/prompts/__init__.py → build_system_prompt()` appends the
matching section to every agent prompt. `applies-to` filters by agent type, so
persona-only skills never leak into `mgr`/`creator` prompts.

> Why is the loader in the Community app and not the kernel? Today Community is the
> only consumer (it builds persona/mgr prompts). The kernel *ships* the base skill
> files so any app — or a future Workspace consumer — can pick them up; promoting the
> loader itself into the kernel is a clean follow-up if a second app needs it.

## Format

```markdown
---
name: <unique-key>
description: <one-line summary>
applies-to: persona | mgr | creator | all
when-to-use: <trigger condition — what prompt segment / situation activates this>
priority: 1-10 (lower = injected first)
---

<body in English — principles, rules, examples in abstract terms, "Never do" list,
core stance / one-line spirit>

→ Korean phrasing examples: see `_examples/<skill>.ko.md`
```

## Why English canonical?

Per `CLAUDE.md`: prompt source is English; locale-specific phrasing (Korean filler
어휘 / honorifics / 카톡 style etc.) is injected via `community/core/prompts/locale.py`
helpers or per-language overrides. Skill files follow the same rule — body in English,
locale examples separate.

## Skills

**Kernel (`glimi/skills/`)**

| Skill | Applies | Priority | Purpose |
|---|---|---|---|
| `ambient-awareness` | all | 8 | Reference other-channel context naturally |
| `conversation-join` | persona | 6 | Enter in-progress group chats |
| `emotional-expression` | persona | 5 | Reflect current emotion in tone |
| `memory-recall` | all | 3 | Reference memory section without reciting |

**Community app (`community/skills/`)**

| Skill | Applies | Priority | Purpose |
|---|---|---|---|
| `meta-question-handling` | persona | 2 | Handle "are you AI?" type questions (domain policy) |

## Adding a new skill

1. Decide the home: generic agent behavior → `glimi/skills/`; app-specific policy →
   `community/skills/` (or your app's skills dir).
2. Create `<key>/SKILL.md` following the format above.
3. Add Korean (or other) examples to `_examples/<key>.ko.md` if needed.
4. Update the relevant table above. **Add a test** in `tests/unit/test_skills.py` if
   it's load-bearing — this whole framework once silently regressed (the inject call
   was dropped in an unrelated commit) because nothing tested it.

## Examples directory (`_examples/`)

Hosts locale-specific phrasing examples that would clutter the canonical English skill
body. Underscore prefix excludes from skill discovery (consistent with the achievements
catalog `_shared.py` pattern).
