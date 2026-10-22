"""vulture whitelist: names that look unused but an interface requires.

Run: uv run vulture src vulture_whitelist.py --min-confidence 80
Unused functions, methods, route handlers and pydantic fields only reach 60%
confidence, so the gated 80% level needs no entries for them. Add an entry
only for a parameter or name an external protocol requires, with the reason.
"""
# ruff: noqa: F821, B018

cls  # @classmethod and pydantic validators (holdings/loader.py, evaluation.py, routes/settings.py)
method_name  # structlog processor signature (logging.py: pii_redaction_processor)
