#!/usr/bin/env bash
# Start `ollama serve` from a terminal with the env AlphaSwarm needs.
#
# - OLLAMA_USE_MLX=1: the nvfp4 model tags only run on the MLX backend
#   (ollama 0.19+, >= 32 GB). Without it Ollama silently falls back to
#   llama.cpp: about 2.8x slower worker prefill and 30x slower orchestrator
#   prefill (docs/DECISIONS.md#adr-model-stack, docs/RUNBOOK.md section 1).
# - OLLAMA_NUM_PARALLEL=4: server-side decode slots. 16 spilled the KV cache to
#   CPU on the M1 Max; 4 is the recorded decision.
# - OLLAMA_MAX_LOADED_MODELS=2: orchestrator + worker at most.
#
# Every value can be overridden from the caller's environment. If you use
# Ollama.app instead, run scripts/configure_ollama_app_env.sh once: it sets the
# same variables via launchctl and persists them across reboots.

set -euo pipefail

export OLLAMA_USE_MLX="${OLLAMA_USE_MLX:-1}"
export OLLAMA_NUM_PARALLEL="${OLLAMA_NUM_PARALLEL:-4}"
export OLLAMA_MAX_LOADED_MODELS="${OLLAMA_MAX_LOADED_MODELS:-2}"
export OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:-5m}"

echo "Starting ollama serve with:"
echo "  OLLAMA_USE_MLX=$OLLAMA_USE_MLX"
echo "  OLLAMA_NUM_PARALLEL=$OLLAMA_NUM_PARALLEL"
echo "  OLLAMA_MAX_LOADED_MODELS=$OLLAMA_MAX_LOADED_MODELS"
echo "  OLLAMA_KEEP_ALIVE=$OLLAMA_KEEP_ALIVE"

exec ollama serve
