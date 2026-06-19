# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""Glimi landing — the standalone entry-hub (portal) app.

A tiny third service alongside the Community (``src.platform``) and Workspace
(``apps.workspace``) apps, so Landing / Community / Workspace are three genuinely
separate services. The portal is pure: a logo, a line of copy, and links out to
the Community and Workspace demos — no DB, no auth, no session.
"""
