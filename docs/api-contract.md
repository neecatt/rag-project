# API Contract Workflow

`openapi.yaml` is the source of truth for backend/frontend/data-ingestion integration.

## Rules

- Contract changes are made before implementation changes.
- Backend endpoints must match `openapi.yaml`.
- Frontend API clients and mocks must follow `openapi.yaml`, not inferred response shapes.
- Data ingestion changes that affect source, document, chunk, status, citation, or job semantics must update `openapi.yaml` and this document when needed.
- PRs that change request/response fields, status values, endpoint paths, query parameters, or error behavior must include a `Contract impact` section.
- If no contract changes are made, PRs must explicitly say `Contract impact: none`.

## Change Flow

1. Update `openapi.yaml`.
2. Update `docs/api-contract.md` if the workflow or semantics changed.
3. Update backend schemas/endpoints.
4. Update frontend API types, mocks, and UI behavior.
5. Update ingestion schemas/metadata/status behavior if affected.
6. Run contract validation and component tests.

## Contract Validation

Local validation:

```bash
npx --yes @redocly/cli lint openapi.yaml
```

CI runs the same OpenAPI validation on every PR.

## Shared Field Semantics

- `document_id`, `source_id`, and `conversation_id` are internal identifiers and may be used for API calls.
- User-facing UI must not render raw UUIDs unless the view is explicitly a developer/debug view.
- `status` for documents is one of `queued`, `processing`, `completed`, or `failed`.
- Chat/search citations must identify the evidence actually used or returned by the backend.
- Citation display should prefer `title`, `locator`, `page_number`, and `section_title` over internal IDs.
- `POST /conversations/{conversation_id}/messages` and `POST /chat` accept a `message` field for user input.
- `POST /chat` returns `404` when a provided `session_id` does not exist.
- `POST /conversations/{conversation_id}/messages` returns `422` when a provided `session_id` does not match the path `conversation_id`.

## Mocking Guidance

- Frontend mocks must be shaped from `openapi.yaml`.
- Mock data should include both success and failure states.
- Mock data must not hide backend contract errors during normal integrated runs.
