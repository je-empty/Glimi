# dashboard_demo

View a Glimi agent population in the **Glimi Core dashboard** — store-driven and
read-only.

`run.py` builds a tiny offline (`echo`) population (a coordinator + two personas,
a few turns, relationships, seeded memory/facts) and serves the dashboard against
that population's store with `glimi.dashboard.serve(store)`.

## Run

```bash
pip install "glimi[dashboard]"          # or, from the monorepo:  pip install -e ".[dashboard]"
PYTHONPATH=. python examples/dashboard_demo/run.py
```

Then open <http://127.0.0.1:8800>.

## What you'll see

- **Connection graph** — agents + owner as nodes; channel co-participation and
  relationships as edges (Cytoscape, same look as Glimi Community).
- **Agents** — click a card for profile, 5-layer memory, semantic facts, and
  relationships.
- **Channels** — click a channel to read its messages.

The dashboard never mutates the store — it only observes it. It makes no
Discord / Community / server-control assumptions, so you can point
`serve(your_store)` at any `KernelStore` population.
