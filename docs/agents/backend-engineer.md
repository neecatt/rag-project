# Backend Engineer Instructions

## Branch

Use `agent/backend`.

```bash
git fetch origin
git checkout agent/backend
git rebase origin/main
```

## Folder Scope

Primary ownership:

- `backend/app/api/**`
- `backend/app/schemas/**`
- `backend/app/services/chat_service.py`
- `backend/app/services/answer_generation.py`
- `backend/app/services/retrieval_service.py`
- `backend/app/retrieval/**`
- `backend/app/models/**`
- `tests/backend/**` for backend, search, chat, schema, and contract tests

Shared ownership by coordination:

- `openapi.yaml`
- `docs/api-contract.md`
- `docs/agent-workflow.md`

Avoid editing:

- `frontend/**`, unless the lead engineer explicitly asks for a contract fixture or generated type update.
- Ingestion internals owned by Data Ingestion Engineer, unless backend API contracts require a small coordinated change.

## Contract Workflow

- Update `openapi.yaml` first for endpoint, schema, status, or error changes.
- Backend schemas and route response models must match `openapi.yaml`.
- If a contract changes, document it in the PR under `Contract impact`.
- If no contract changes, write `Contract impact: none`.

## Commit, Push, PR

Before pushing:

```bash
backend/.venv/bin/pytest tests/backend -q
npx --yes @redocly/cli lint openapi.yaml
```

Then:

```bash
git status --short
git add <changed-files>
git commit -m "backend: <short summary>"
git push -u origin agent/backend
gh pr create --draft --base main --head agent/backend --title "Backend: <summary>" --body-file <pr-body-file>
```

## Conflict Avoidance

- Rebase from `origin/main` after any merged PR.
- Do not rewrite frontend response handling without frontend coordination.
- Do not silently change document/source/citation fields; update `openapi.yaml` first.
