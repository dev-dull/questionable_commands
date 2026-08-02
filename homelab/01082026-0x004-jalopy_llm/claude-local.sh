# Point Claude Code at the homelab box.  Usage:  source claude-local.sh

export CLAUDE_CODE_AUTO_COMPACT_WINDOW=65536   # must match llama-server's -c
export ANTHROPIC_BASE_URL=http://192.168.1.223:8080
export ANTHROPIC_AUTH_TOKEN=local
export ANTHROPIC_MODEL=coder
export ANTHROPIC_SMALL_FAST_MODEL=coder

# unset, not set-to-empty: an empty ANTHROPIC_API_KEY still wins its slot in
# credential resolution and would authenticate against the real Anthropic API.
unset ANTHROPIC_API_KEY
