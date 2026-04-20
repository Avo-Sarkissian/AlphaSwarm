"""Unit test package — pure Python tests with Fakes only, no network, no Neo4j, no Ollama.

pytest-socket --disable-socket applies project-wide; tests in this directory
MUST NOT use @pytest.mark.enable_socket.
"""
