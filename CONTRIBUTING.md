# Contributing

Read AGENTS.md and DEVELOPMENT_PLAN.md. Use Python 3.12 with `uv sync --locked --group dev`; run `uv run pytest`, `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, and `uv run mypy src/chattwin`. Build the UI with `sh scripts/build_web.sh`. Commit schemas and generated TypeScript whenever contracts change.

Only synthetic fixtures belong in tests. Do not submit conversations, identifiers, credentials, databases, training datasets or private adapters. Core domain has no database/framework/channel SDK imports; conversation generates candidates; only outbox invokes channel transport. Changes to the transport-start barrier need a failing race regression first.

Label evidence synthetic, real local, or real external. A protocol fixture is not QQ validation; tiny training is not Qwen quality acceptance. See docs/tasks.md for actual task status. Public pushes and releases are manual owner actions.
