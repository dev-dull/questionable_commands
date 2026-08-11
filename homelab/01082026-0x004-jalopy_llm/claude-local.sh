# Point Claude Code at the homelab box.  Usage:  source claude-local.sh
#
# Standalone equivalent of ansible/roles/clients, which installs a `local-claude`
# wrapper instead. Kept because it is readable without running the playbook — but
# the two MUST stay in sync. If you change -c or -np in
# ansible/inventory/group_vars/aihost.yml, update both.
#
# Prefer the wrapper if you have it. Sourcing this exports into your shell, so
# plain `claude` is also redirected at the local box until you open a new one.

export ANTHROPIC_BASE_URL=http://192.168.1.223:8080
export ANTHROPIC_AUTH_TOKEN=local
export ANTHROPIC_MODEL=coder
export ANTHROPIC_SMALL_FAST_MODEL=coder

# unset, not set-to-empty: an empty ANTHROPIC_API_KEY still wins its slot in
# credential resolution and would authenticate against the real Anthropic API.
unset ANTHROPIC_API_KEY

# Claude Code defaults this to the MODEL's context window — 200K for standard
# models — and its lookup fails on gateway aliases like `coder`. Unset means it
# will not compact until ~167K against a server that stops at 131K.
#
# Derive from usable context PER SLOT: `-c` divided by `-np`.
#   coder runs -c 131072 -np 1  ->  131072 per request.
#
# Then set it BELOW that, never equal. At equal, the compaction budget and the
# server's hard limit are the same number: auto-compact fires with no room left
# to run in, and /compact fails too, because compaction is itself a request that
# must fit inside the window it is trying to free. Nothing rescues you from it —
# Claude Code's reactive compaction only recognises Anthropic's "prompt too
# long" phrasing, not llama.cpp's.
export CLAUDE_CODE_AUTO_COMPACT_WINDOW=98304   # 75% of 131072

# Alternative lever: leave the window at the true per-slot figure and move the
# trigger instead, which survives a -c change without recomputation.
#   export CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=75
