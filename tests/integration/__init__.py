"""tests/integration — opt-in real-network integration tests.

The conftest.py in this directory auto-applies @pytest.mark.enable_socket to
every test in this subtree (D-12).

At Phase 37, this directory has no real tests — only the smoke test that
verifies the auto-marker works. Later phases (38, 39, 43) that need real
network access (Ollama, Neo4j, yfinance, RSS) will populate this directory.
"""
