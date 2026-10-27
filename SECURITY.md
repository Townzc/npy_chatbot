# Security and private data

The application defaults to loopback and requires a local owner token. Never put that token in a URL. Use separate credentials for owner control, the model endpoint and OneBot. No default telemetry or uploads. `chat_record/` is ignored input; runtime directories are rejected inside Git worktrees.

Send a minimal synthetic reproduction when reporting a security issue. Do not post chat logs, databases, tokens, account IDs or model weights in public issues. This pre-release has not had an independent security audit. Mobile/remote access is not yet supported by the CLI; do not expose its port publicly.

If credentials leak, stop the service and rotate the affected credentials using their owner-managed mechanism. An uncertain platform send is not automatically retried. Existing model weights do not forget deleted source material.

The [2026-10-27 dependency review](docs/evidence/dependency-review-2026-10-27.md) still has OSV findings for the pinned training stack. Vite and filelock were updated; model configuration checks reduce specific loading risks but do not replace patched upstream dependencies or an audit. The current training backend accepts only the pinned reference Qwen revision and code-free local synthetic tiny Qwen3 inputs. Do not load unreviewed model repositories or treat `trust_remote_code=False` as a sandbox. Production release remains blocked.

Regenerate `docs/sbom.cdx.json`, then run `uv run python scripts/audit_dependencies.py --licenses --output /tmp/chattwin-audit.json` to check the locked package inventory. Exit 1 means findings and exit 2 means incomplete checks. Registry license metadata does not establish redistribution rights; external bridges and model weights require separate review.
