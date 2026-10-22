"""tests/integration — live tests against real third-party services.

Every module here is marked ``live_network`` (or ``ollama``) and is skipped unless
``--run-live`` is given. Sockets come from those markers, never from this directory
(docs/DECISIONS.md#adr-test-network-gate).
"""
