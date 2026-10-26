# Security and private data

The application defaults to loopback and requires a local owner token. Never put that token in a URL. Use separate credentials for owner control, the model endpoint and OneBot. No default telemetry or uploads. `chat_record/` is ignored input; runtime directories are rejected inside Git worktrees.

Send a minimal synthetic reproduction when reporting a security issue. Do not post chat logs, databases, tokens, account IDs or model weights in public issues. This pre-release has not had an independent security audit. Mobile/remote access is not yet supported by the CLI; do not expose its port publicly.

If credentials leak, stop the service and rotate the affected credentials using their owner-managed mechanism. An uncertain platform send is not automatically retried. Existing model weights do not forget deleted source material.
