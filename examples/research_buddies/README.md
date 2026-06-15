# research_buddies

Two research agents — **Nova** and **Atlas** — collaborate on a topic by taking
turns on a single shared channel. Each turn builds on what the other just said.

## What it shows

- The **convenience API** (`from glimi import Glimi`): wire two agents in a few lines.
- A **shared in-memory store**: both agents live in one `Glimi` instance, so
  everything one writes is readable by the other. The script reads the partner's
  previous contribution back out of the shared channel history (not a Python
  variable) before each turn, and prints the full shared log at the end.
- The **planner/collaborator handoff via the store** — the store is the bus the
  agents talk through.

## Run

Offline, zero dependencies, no API key (default `echo` backend):

```bash
# from the repo root, before `pip install glimi` lands:
PYTHONPATH=. python examples/research_buddies/run.py
```

Once `pip install glimi` is available, from this folder:

```bash
python run.py
```

## Backends

`echo` is the **offline placeholder** backend (the default): it just echoes your
last line, so the collaboration is illustrative, not real. Swap in a real model
for genuine reasoning:

```bash
GLIMI_LLM_BACKEND=claude_cli python run.py     # needs the Claude CLI
python run.py --backend ollama                 # needs a local Ollama
```

Set the backend via the `GLIMI_LLM_BACKEND` env var or the `--backend` flag.

## Sample output (real backend: claude_cli)

Generated with the `claude_cli` backend (the local Claude CLI subprocess); the
`echo` backend is the offline default. The runtime startup banner is trimmed;
the agent turns are verbatim.

```text
=== research_buddies (backend: claude_cli) ===
Using a real backend — expect genuine, model-generated turns.

--- Lead opens the investigation ---
[Runtime] Nova (nova) 활성화
Nova: Here's my opening puzzle: **we get two tidal bulges, not one.**
The obvious story is the Moon pulls seawater toward it—makes sense. But why does the *opposite* side of Earth also bulge? That's the tell. It suggests tides aren't just about the Moon's gravity pulling stuff, but about *differential* gravity—the Moon pulling harder on the near side than the far side, stretching Earth like taffy.
Hypothesis:** The mechanism that matters is the *gradient* in gravitational force across Earth's radius, not the absolute force itself. That's why the Sun, despite being massive, causes smaller tides—it's farther away, so its pull doesn't vary as much across Earth's diameter.
Want to dig into whether that holds water? And then we can get weird: why some harbors have wild tides while others barely budge despite sitting on the same ocean.

--- Atlas builds on the partner's last point ---
[Runtime] Atlas (atlas) 활성화
Atlas: Here's the wrinkle:** the tidal bulge itself isn't the whole story. Earth's oceans are *sloshing in basins*, and some of those basins have a natural resonance frequency that matches how the tidal wave tries to slosh them.
Concrete example—the Bay of Fundy:** its geometry and depth create a resonance that amplifies the incoming tidal wave. The water gets funneled into a narrowing channel, and it oscillates back and forth at just the right frequency to reinforce itself. Result: 50+ foot tides. Meanwhile, the Mediterranean barely budges—it's too small and enclosed for the tidal period to resonate properly.
The testable claim:** it's not just about *how much* the Moon pulls; it's about whether Earth's ocean basins can *ring* like a bell at that frequency. Change the basin geometry, and you change the tide amplitude—even if the gravitational forcing stays identical.
That explains why you can sail from a megamoon-tide location to a sheltered harbor nearby and see almost nothing. The Moon's pulling equally on both, but one basin is locked into amplification while the other one dampens out the oscillations through friction and geometry.
So now the question sharpens: **does the math predict which basins amplify and which don't?** And does it account for why tides got steadily larger from the Mediterranean through the Atlantic and into funnel-shaped bays?

--- Nova builds on the partner's last point ---
Nova: Nova here. Building on that:
Here's the wrinkle to the wrinkle: the tidal bulge doesn't actually exist on real ocean maps.**
When you look at actual tidal data—co-tidal lines, the places where high tide happens at the same moment—you don't see two clean bulges sweeping around the planet. Instead, you see *rotating amphidromic systems*: points where the tidal range is nearly zero, surrounded by tidal crests that spiral around them like water going down a drain (or up, depending on hemisphere).
That's the **Coriolis effect** doing the heavy lifting. As the tidal wave tries to slosh, Earth's rotation deflects it sideways. In the Northern Hemisphere, a wave moving "outward" from the tidal bulge gets pushed to the right, which forces it to rotate around a central amphidromic point. The tidal wave doesn't propagate outward—it *rotates*.
The prediction:** if Coriolis is real, tidal range shouldn't be symmetric around the equator. North Atlantic tides should spiral one way, South Atlantic another. And those amphidromic points should be in the *exact* places where basin geometry + Coriolis balance out to cancel the tide amplitude.
The test that breaks it open:** can you predict *where the amphidromic points are* just from basin shape and latitude? If the math nails it, you've cracked the full three-part system—gravity sets the forcing, basin geometry amplifies it, and Coriolis sculpts the final pattern into those weird rotating knots.
What's your hypothesis—does the math actually predict where the amphidromic points land?

--- Shared research log (one store, both agents) ---
  Lead: Let's investigate how tides work. Open with one idea.
  Nova: Here's my opening puzzle: **we get two tidal bulges, not one.**
  Nova: The obvious story is the Moon pulls seawater toward it—makes sense. But why does the *opposite* side of Earth also bulge? That's the tell. It suggests tides aren't just about the Moon's gravity pulling stuff, but about *differential* gravity—the Moon pulling harder on the near side than the far side, stretching Earth like taffy.
  Nova: Hypothesis:** The mechanism that matters is the *gradient* in gravitational force across Earth's radius, not the absolute force itself. That's why the Sun, despite being massive, causes smaller tides—it's farther away, so its pull doesn't vary as much across Earth's diameter.
  Nova: Want to dig into whether that holds water? And then we can get weird: why some harbors have wild tides while others barely budge despite sitting on the same ocean.
  Lead: Your partner just said: "Want to dig into whether that holds water? And then we can get weird: why some h…" — build on it with one new point about how tides work.
  Atlas: Here's the wrinkle:** the tidal bulge itself isn't the whole story. Earth's oceans are *sloshing in basins*, and some of those basins have a natural resonance frequency that matches how the tidal wave tries to slosh them.
  Atlas: Concrete example—the Bay of Fundy:** its geometry and depth create a resonance that amplifies the incoming tidal wave. The water gets funneled into a narrowing channel, and it oscillates back and forth at just the right frequency to reinforce itself. Result: 50+ foot tides. Meanwhile, the Mediterranean barely budges—it's too small and enclosed for the tidal period to resonate properly.
  Atlas: The testable claim:** it's not just about *how much* the Moon pulls; it's about whether Earth's ocean basins can *ring* like a bell at that frequency. Change the basin geometry, and you change the tide amplitude—even if the gravitational forcing stays identical.
  Atlas: That explains why you can sail from a megamoon-tide location to a sheltered harbor nearby and see almost nothing. The Moon's pulling equally on both, but one basin is locked into amplification while the other one dampens out the oscillations through friction and geometry.
  Atlas: So now the question sharpens: **does the math predict which basins amplify and which don't?** And does it account for why tides got steadily larger from the Mediterranean through the Atlantic and into funnel-shaped bays?
  Lead: Your partner just said: "So now the question sharpens: **does the math predict which basins amplify and w…" — build on it with one new point about how tides work.
  Nova: Nova here. Building on that:
  Nova: Here's the wrinkle to the wrinkle: the tidal bulge doesn't actually exist on real ocean maps.**
  Nova: When you look at actual tidal data—co-tidal lines, the places where high tide happens at the same moment—you don't see two clean bulges sweeping around the planet. Instead, you see *rotating amphidromic systems*: points where the tidal range is nearly zero, surrounded by tidal crests that spiral around them like water going down a drain (or up, depending on hemisphere).
  Nova: That's the **Coriolis effect** doing the heavy lifting. As the tidal wave tries to slosh, Earth's rotation deflects it sideways. In the Northern Hemisphere, a wave moving "outward" from the tidal bulge gets pushed to the right, which forces it to rotate around a central amphidromic point. The tidal wave doesn't propagate outward—it *rotates*.
  Nova: The prediction:** if Coriolis is real, tidal range shouldn't be symmetric around the equator. North Atlantic tides should spiral one way, South Atlantic another. And those amphidromic points should be in the *exact* places where basin geometry + Coriolis balance out to cancel the tide amplitude.
  Nova: The test that breaks it open:** can you predict *where the amphidromic points are* just from basin shape and latitude? If the math nails it, you've cracked the full three-part system—gravity sets the forcing, basin geometry amplifies it, and Coriolis sculpts the final pattern into those weird rotating knots.
  Nova: What's your hypothesis—does the math actually predict where the amphidromic points land?

Done. Both agents read and wrote the same shared channel history.
```

## Note: keep demos short

The demo runs only a couple of exchanges on purpose. The memory layer rolls up
raw messages into L1 summaries once a channel passes `L1_BATCH_SIZE` (5) messages
(`glimi/memory.py`). On this branch the rollup path has a known
offset-naive/aware datetime bug in `get_memory_context` (fixed separately in
`fix/memory-tz`). Keeping each channel under the threshold avoids it. The offline
`echo` backend never populates memories anyway, so it is always clean; the caveat
matters mainly for real backends.
