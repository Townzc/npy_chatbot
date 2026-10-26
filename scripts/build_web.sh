#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
# Codex desktop provides a bundled Node runtime; normal Node installs work too.
if ! command -v node >/dev/null 2>&1; then
  runtime="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies"
  if [ -x "$runtime/node/bin/node" ]; then
    PATH="$runtime/node/bin:$runtime/bin/fallback:$PATH"
    export PATH
  else
    echo "Install Node.js 22+ and pnpm 10 before building the web app." >&2
    exit 1
  fi
fi
uv run python scripts/export_schema.py
cd apps/web
pnpm install --frozen-lockfile
pnpm generate:api
pnpm build
cd ../..
mkdir -p src/chattwin/web_dist
cp -R apps/web/dist/. src/chattwin/web_dist/
