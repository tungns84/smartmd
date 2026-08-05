# Testing

Baseline coverage floors captured **2026-08-04** (pre-refactor). Floors live in
`coverage-floors.json` at the repo root and only ratchet upward via
`scripts/coverage_gate.py --update`.

## Three speed tiers

| Tier | Command | Needs |
|------|---------|-------|
| Unit (inner loop) | `uv run pytest -m "not db and not integration"` | Nothing |
| App (`db`) | `uv run pytest -m db` | `TEST_DATABASE_URL` (Postgres); skips if missing |
| Integration | `uv run pytest -m integration` | `PDF2MD_WEB_E2E=1` + Postgres + Redis + worker |

Default `uv run pytest` runs all collected tests (`addopts = "-q"`). Missing env
for `db` / `integration` / OCR e2e skips with a clear reason — it does not fail.

## Before commit (coverage ratchet)

```bash
uv run pytest --cov=smart_pdf2md --cov-report=json -q
uv run python scripts/coverage_gate.py
```

Gated modules (silent-failure risk): `cache.py`, `converter.py`, `env.py`,
`merge.py`, `ocr/opencode_backend.py`, `ocr/opencode_pricing.py`. Later cycles
add VLM registry/dialects and web security/credits to the same list in
`scripts/coverage_gate.py`.

`cli.py` and `progress.py` are omitted from coverage; CLI presentation is locked
by golden tests in `tests/test_cli_output_contract.py`.

## Raise a floor (ratchet up)

After new tests raise coverage on a gated module:

```bash
uv run pytest --cov=smart_pdf2md --cov-report=json -q
uv run python scripts/coverage_gate.py --update
```

`--update` never lowers a floor. Review the diff of `coverage-floors.json` in git.

## Golden CLI contracts

Approved fixtures: `tests/golden/cli/*.approved.txt`. On mismatch the
harness writes `*.actual.txt` beside them. To accept an intentional CLI change,
replace the approved file with the actual file and commit both the fixture and
the reason in the commit message.

## Markers

Defined in `pyproject.toml`:

- `db` — needs DB via `TEST_DATABASE_URL` (Postgres preferred; SQLite works for most web tests). Concurrent credit overdraft requires Postgres.
- `integration` — real services, gated by `PDF2MD_WEB_E2E=1`
- `slow` — large fixture PDFs

## Web tests without Docker

```bash
# PowerShell example (SQLite)
$env:TEST_DATABASE_URL = "sqlite+pysqlite:///./.testdb.sqlite"
uv run pytest tests/web -q
```

Skipped when env missing: `db` tests, `integration` tests, OCR e2e (`PDF2MD_OCR_E2E`).
