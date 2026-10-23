"""Service layer shared by the CLI and the web app (docs/DECISIONS.md#adr-web-lifespan).

Modules: ``runtime`` (composition root and inference runtime), ``jobs``
(background orchestrator jobs), ``report``, ``advisory`` and ``post_run``.
Nothing is re-exported here, so importing one service never imports the others.
"""
