# Contributing to TokenProof

TokenProof is an open-source shared compliance infrastructure layer for the Canton Network, licensed under Apache 2.0. Contributions are welcome from Canton developers, compliance engineers, and regulatory technologists.

---

## Before you start

- Read [docs/architecture.md](docs/architecture.md) to understand the four-layer design.
- Read [docs/quickstart.md](docs/quickstart.md) and get `dpm test` passing locally before submitting any PR.
- Check open issues before opening a new one to avoid duplicates.

---

## How to run the full test suite locally

```bash
# DAML contracts — all three packages
export PATH="$HOME/.dpm/bin:/opt/homebrew/opt/openjdk@17/bin:$PATH"
dpm build --all
cd daml && dpm test
cd ../examples/cip0056-gated-transfer && dpm test
cd ../stablecoin-genius-act && dpm test

# Backend
cd ../../backend
pip install -r requirements.txt
python -m pytest tests/ -v
```

All five DAML scripts and all backend unit tests must pass before a PR will be reviewed.

---

## Types of contribution

### New policy pack

Each policy pack is a single Python file in `backend/policy_packs/`. A policy pack must:

1. Expose an `evaluate(metadata: dict) -> dict` function.
2. Return `classification`, `policyVersion`, `passed`, and `controlResults`.
3. Use worst-of aggregation: one failing control means `mixed_or_unclassified`.
4. Be deterministic — no randomness, no external API calls, no timestamps.
5. Include a corresponding test in `backend/tests/test_policy_packs.py`.

Register it in `backend/policy_packs/__init__.py` under `REGISTRY`.

### DAML contract changes

- All DAML changes must keep the `dpm test` suite passing.
- Authorization patterns must be correct: signatories must co-authorize contract creation.
- Do not add global contract keys — Canton 3.4 / Daml-LF 2.x removed them. Use explicit `ContractId` passing.

### Documentation

- Architecture claims in `docs/architecture.md` must match the actual DAML source.
- Port numbers, API paths, and method names must match the live implementation.
- Mermaid diagrams are preferred over ASCII art.

---

## Pull request process

1. Fork the repository and create a branch from `main`.
2. Make your changes and ensure all tests pass.
3. Add a short entry to `CHANGELOG.md` under `[Unreleased]`.
4. Open a PR with a clear description of what changed and why.
5. Sign your commits with the Apache 2.0 DCO: `Signed-off-by: Your Name <email>`.

---

## Proposing a new feature

Open a GitHub Issue with the label `proposal`. Describe:

- The problem it solves
- The layer it touches (DAML / backend / SDK / docs)
- Any breaking changes to existing contract or API shapes

---

## Code style

- **DAML**: follow the existing signatory/observer pattern; add comments explaining authorization intent.
- **Python**: formatted with `ruff`; no external runtime dependencies beyond `requirements.txt`.
- **TypeScript**: strict mode; no `any`.

---

## License

By contributing you agree that your contribution is licensed under Apache 2.0 and that you have the right to grant that license. See [LICENSE](LICENSE).
