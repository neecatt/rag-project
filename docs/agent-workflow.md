# Multi-Agent GitHub Workflow

This project uses a contract-first, branch-isolated workflow for three implementation agents and one lead engineer.

## Branch Structure

- `main`: stable integration branch. No direct agent pushes.
- `agent/backend`: Backend Engineer branch.
- `agent/frontend`: Frontend Engineer branch.
- `agent/data-ingestion`: Data Ingestion Engineer branch.
- `integration/backend-frontend`: temporary branch for major cross-component integration when needed.

The local repository may still be on `master`. Normalize it once before starting agent work:

```bash
git branch -M main
git push -u origin main
```

## Initial Branch Setup

```bash
git fetch origin
git checkout main
git pull --ff-only origin main
git checkout -B agent/backend main
git push -u origin agent/backend
git checkout -B agent/frontend main
git push -u origin agent/frontend
git checkout -B agent/data-ingestion main
git push -u origin agent/data-ingestion
```

Optional local worktrees:

```bash
mkdir -p ../rag-worktrees
git worktree add ../rag-worktrees/backend agent/backend
git worktree add ../rag-worktrees/frontend agent/frontend
git worktree add ../rag-worktrees/data-ingestion agent/data-ingestion
```

## Contract-First Rules

- `openapi.yaml` is the source of truth for HTTP integration.
- Contract changes land before implementation that depends on them.
- Backend implements `openapi.yaml`.
- Frontend consumes `openapi.yaml` and contract-shaped mocks.
- Data ingestion follows the same source/document/status/citation schemas.
- Contract-changing PRs must state the impact clearly.

## PR Rules

- Each agent pushes only to their own branch.
- Each agent opens a draft PR into `main`.
- No agent pushes directly to `main`.
- Every PR must include:
  - Summary
  - Tests run
  - Contract impact
  - Risk/rollback notes when relevant
- PRs remain draft until local tests pass.
- Merging requires CI passing and lead engineer review.

## Rebase Rules

After any PR merges into `main`, all other agents must run:

```bash
git fetch origin
git checkout <agent-branch>
git rebase origin/main
git push --force-with-lease
```

If a rebase touches `openapi.yaml`, stop and ask the lead engineer to resolve the contract ordering.

## Integration Branch

Use `integration/backend-frontend` when backend and frontend changes must be tested together before merging:

```bash
git fetch origin
git checkout -B integration/backend-frontend origin/main
git merge --no-ff origin/agent/backend
git merge --no-ff origin/agent/frontend
docker compose up -d --build
```

Only the lead engineer owns integration branches.

## CI Checklist

- Backend tests: `backend/.venv/bin/pytest tests/backend -q`
- Frontend build/typecheck: `npm run build`
- Data ingestion tests: chunking, extraction, and ingestion service tests
- OpenAPI validation: `npx --yes @redocly/cli lint openapi.yaml`
- Optional E2E: upload, processing, search, chat, citation display

## Conflict Avoidance

- Backend Engineer should not edit frontend components.
- Frontend Engineer should not edit backend services except contract-generated fixtures or docs after coordination.
- Data Ingestion Engineer should not edit chat UI or answer generation.
- Shared files such as `openapi.yaml`, `docs/api-contract.md`, and shared type docs require contract-first coordination.
