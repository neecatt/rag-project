# Frontend Engineer Instructions

## Branch

Use `agent/frontend`.

```bash
git fetch origin
git checkout agent/frontend
git rebase origin/main
```

## Folder Scope

Primary ownership:

- `frontend/src/app/**`
- `frontend/src/components/**`
- `frontend/src/lib/api.ts`
- `frontend/src/lib/types.ts`
- `frontend/src/lib/demo-data.ts`
- `frontend/package.json`
- `frontend/package-lock.json`
- frontend tests if added

Shared ownership by coordination:

- `openapi.yaml`
- `docs/api-contract.md`

Avoid editing:

- `backend/app/**`, except generated or contract fixture files when explicitly coordinated.
- `backend/app/ingestion/**` and ingestion services.

## Contract Workflow

- Frontend API client behavior must follow `openapi.yaml`.
- Do not guess response shapes from manual testing.
- If the UI needs a backend field that is not in `openapi.yaml`, request or make the contract change first.
- Mocks must use contract-shaped responses.
- Normal user-facing UI must not render raw UUIDs unless inside a clearly marked developer/debug view.

## Commit, Push, PR

Before pushing:

```bash
npm run build
npx --yes @redocly/cli lint openapi.yaml
```

Then:

```bash
git status --short
git add <changed-files>
git commit -m "frontend: <short summary>"
git push -u origin agent/frontend
gh pr create --draft --base main --head agent/frontend --title "Frontend: <summary>" --body-file <pr-body-file>
```

## Conflict Avoidance

- Rebase from `origin/main` after any merged PR.
- Keep API normalization centralized in `frontend/src/lib/api.ts`.
- Do not patch around backend bugs with invented frontend data; raise the contract/backend issue.
