# Production TODO

- Replace placeholder chat generation with a real LLM orchestration pipeline and citation grounding.
- Replace placeholder ingestion with persistent jobs, retry handling, and worker execution via Redis-backed queues.
- Add SQL migrations instead of relying on startup `create_all`.
- Implement real tenant isolation, authentication, and RBAC.
- Add pgvector-backed embedding generation and retrieval over persisted chunks.
- Add source sync connectors and secure secret management.
- Add request logging, tracing, metrics, and audit log persistence.
- Add CI build/lint steps for deterministic frontend verification.
- Consolidate duplicated test/layout scaffolding such as empty `backend/tests/` versus active `tests/backend/`, and empty `infra/docker/` versus active top-level `docker/`.
