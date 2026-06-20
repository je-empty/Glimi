"""App-side adapters that bind the Glimi kernel's abstract interfaces
(``glimi.store`` / ``profiles`` / ``observability``) to the Community app's
concrete layers (``community.db``, ``community.core.profile``, ``community.log_writer``).

The kernel never imports these; the app injects them at the edge.
"""
