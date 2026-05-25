# Data Ingestion Engineer Instructions

## Branch

Use `agent/data-ingestion`.

```bash
git fetch origin
git checkout agent/data-ingestion
git rebase origin/main
```

## Folder Scope

Primary ownership:

- `backend/app/services/ingestion.py`
- `backend/app/services/text_extraction.py`
- `backend/app/ingestion/**`
- `backend/app/services/storage.py`
- ingestion-related models when required
- `tests/backend/test_ingestion_service.py`
- `tests/backend/test_text_extraction.py`
- `tests/backend/test_chunking.py`
- `backend/tests/integration/**`

Shared ownership by coordination:

- `openapi.yaml`
- `docs/api-contract.md`
- document/source/status/citation schema tests

Avoid editing:

- `frontend/**`
- chat answer generation, except when ingestion metadata contract changes require coordinated test updates.

## Contract Workflow

- Any change to document status values, upload responses, source sync responses, document metadata exposed through APIs, or citation locator semantics must update `openapi.yaml` first.
- Ingestion must preserve document/source schemas used by backend and frontend.
- Reprocessing must keep chunk and embedding lifecycle behavior consistent with the contract.

## Commit, Push, PR

Before pushing:

```bash
backend/.venv/bin/pytest tests/backend/test_ingestion_service.py tests/backend/test_text_extraction.py tests/backend/test_chunking.py -q
backend/.venv/bin/pytest tests/backend -q
npx --yes @redocly/cli lint openapi.yaml
```

Then:

```bash
git status --short
git add <changed-files>
git commit -m "ingestion: <short summary>"
git push -u origin agent/data-ingestion
gh pr create --draft --base main --head agent/data-ingestion --title "Ingestion: <summary>" --body-file <pr-body-file>
```

## Conflict Avoidance

- Rebase from `origin/main` after any merged PR.
- Do not change API-visible document fields without coordinating with Backend and Frontend.
- Keep parsing/chunking changes covered by focused tests.
