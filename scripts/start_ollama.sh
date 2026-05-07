#!/usr/bin/env bash
# Start Ollama with AlphaSwarm-required env vars.
#
# Why: AlphaSwarm dispatches up to 100 concurrent /api/chat calls per round
# (batch_dispatcher.py). Without OLLAMA_NUM_PARALLEL set, ollama serves
# requests near-serially and per-call wall-clock balloons to 14-20 min as
# requests stack in the queue (Phase 41.4 Bug B). Setting NUM_PARALLEL=16
# lets ollama batch concurrent decodes; on M1 Max 64GB the 9B q4 worker
# fits 16 slots of num_ctx=4096 KV cache comfortably.
#
# Use this script when running ollama from the terminal. If you use the
# Ollama.app, run scripts/configure_ollama_app_env.sh once instead — it
# sets the same vars via launchctl so the app picks them up on next start.

set -euo pipefail

export OLLAMA_NUM_PARALLEL="${OLLAMA_NUM_PARALLEL:-4}"
export OLLAMA_MAX_LOADED_MODELS="${OLLAMA_MAX_LOADED_MODELS:-2}"
export OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:-5m}"

echo "Starting ollama serve with:"
echo "  OLLAMA_NUM_PARALLEL=$OLLAMA_NUM_PARALLEL"
echo "  OLLAMA_MAX_LOADED_MODELS=$OLLAMA_MAX_LOADED_MODELS"
echo "  OLLAMA_KEEP_ALIVE=$OLLAMA_KEEP_ALIVE"

exec ollama serve
