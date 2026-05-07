#!/usr/bin/env bash
# One-time configure macOS Ollama.app environment for AlphaSwarm.
#
# launchctl setenv writes user-scoped env vars that Ollama.app reads on
# launch. After running this you must quit Ollama.app from the menu bar
# and relaunch it (or `osascript -e 'quit app "Ollama"'` then `open -a Ollama`).
#
# Reverse with: launchctl unsetenv OLLAMA_NUM_PARALLEL OLLAMA_MAX_LOADED_MODELS OLLAMA_KEEP_ALIVE

set -euo pipefail

launchctl setenv OLLAMA_NUM_PARALLEL 4
launchctl setenv OLLAMA_MAX_LOADED_MODELS 2
launchctl setenv OLLAMA_KEEP_ALIVE 5m

echo "launchctl env set:"
echo "  OLLAMA_NUM_PARALLEL=$(launchctl getenv OLLAMA_NUM_PARALLEL)"
echo "  OLLAMA_MAX_LOADED_MODELS=$(launchctl getenv OLLAMA_MAX_LOADED_MODELS)"
echo "  OLLAMA_KEEP_ALIVE=$(launchctl getenv OLLAMA_KEEP_ALIVE)"
echo ""
echo "Now quit and relaunch Ollama.app for these to take effect."
