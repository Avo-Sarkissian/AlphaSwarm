#!/usr/bin/env bash
# Configure macOS Ollama.app environment for AlphaSwarm.
#
# launchctl setenv writes user-scoped env vars that Ollama.app reads on
# launch — but they DO NOT SURVIVE A REBOOT. (Discovered 2026-06-11: a
# reboot silently dropped OLLAMA_NUM_PARALLEL and the swarm ran serially.)
# This script therefore also installs a login LaunchAgent that re-applies
# the vars at every login, before Ollama.app starts.
#
# After running this you must quit Ollama.app and relaunch it:
#   pkill -TERM -f "Ollama.app/Contents/MacOS/Ollama"; sleep 3; open -a Ollama
#
# Reverse with:
#   launchctl unsetenv OLLAMA_NUM_PARALLEL OLLAMA_MAX_LOADED_MODELS OLLAMA_KEEP_ALIVE OLLAMA_USE_MLX
#   launchctl unload ~/Library/LaunchAgents/com.alphaswarm.ollama-env.plist
#   rm ~/Library/LaunchAgents/com.alphaswarm.ollama-env.plist

set -euo pipefail

VARS=(
  "OLLAMA_NUM_PARALLEL 4"
  "OLLAMA_MAX_LOADED_MODELS 2"
  "OLLAMA_KEEP_ALIVE 5m"
  # MLX backend opt-in (ollama 0.19+, needs >=32GB unified memory).
  # Only engages for MLX-format model tags (e.g. qwen3.5:35b-a3b-nvfp4);
  # GGUF tags silently use the llama.cpp Metal path.
  "OLLAMA_USE_MLX 1"
)

for pair in "${VARS[@]}"; do
  # shellcheck disable=SC2086
  launchctl setenv $pair
done

# Persist across reboots: login LaunchAgent re-applies the same vars.
PLIST="$HOME/Library/LaunchAgents/com.alphaswarm.ollama-env.plist"
SETENV_CMD=""
for pair in "${VARS[@]}"; do
  SETENV_CMD+="launchctl setenv $pair; "
done
cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <!-- AlphaSwarm: persist Ollama.app env across reboots.
         Managed by scripts/configure_ollama_app_env.sh -->
    <key>Label</key>
    <string>com.alphaswarm.ollama-env</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/sh</string>
        <string>-c</string>
        <string>${SETENV_CMD}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
PLIST_EOF
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load -w "$PLIST"

echo "launchctl env set (and persisted via $PLIST):"
echo "  OLLAMA_NUM_PARALLEL=$(launchctl getenv OLLAMA_NUM_PARALLEL)"
echo "  OLLAMA_MAX_LOADED_MODELS=$(launchctl getenv OLLAMA_MAX_LOADED_MODELS)"
echo "  OLLAMA_KEEP_ALIVE=$(launchctl getenv OLLAMA_KEEP_ALIVE)"
echo "  OLLAMA_USE_MLX=$(launchctl getenv OLLAMA_USE_MLX)"
echo ""
echo "Now quit and relaunch Ollama.app for these to take effect."
