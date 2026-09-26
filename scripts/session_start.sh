#!/usr/bin/env bash
# SessionStart hook: injects the knowledge-base briefing into every Claude Code session.
# It must never break a session, so every failure is swallowed.
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 0
if ! python3 -c 'import yaml' >/dev/null 2>&1; then
  python3 -m pip install --quiet pyyaml >/dev/null 2>&1 || true
fi
./tj status 2>&1 || echo "tj status failed: run ./tj validate to diagnose."
exit 0
