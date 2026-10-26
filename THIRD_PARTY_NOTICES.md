# Third-party boundaries

New ChatTwin core is Apache-2.0. Dependency packages retain their own licenses. `uv.lock`, `training/uv.lock` and `apps/web/pnpm-lock.yaml` pin the actual dependency graph; a complete release SBOM/license review is still T29, not yet complete.

- ChatLab v0.0.2: independently implemented format reader; upstream is AGPL-3.0. No ChatLab application code bundled.
- QCE: parser not claimed supported without a versioned fixture; GPL-3.0 exporter not bundled.
- NapCatQQ: optional user-run external bridge, custom Limited Redistribution License. Not bundled, downloaded, installed or relicensed. Installer's MIT license is distinct. Exact checked commits and sources are in docs/preflight.md.
- Qwen/Qwen3-4B-Instruct-2507: Apache-2.0 reference candidate, fixed revision in TrainingSpec. No base weights/private adapters bundled.
- Transformers, PEFT, PyTorch and associated packages: independent training environment; upstream licenses apply.

Generated lockfiles and API schemas are project metadata. All included chat fixtures are fictional. Real local data has not been copied into this repository.
