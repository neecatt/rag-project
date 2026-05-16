# Enterprise Knowledge Assistant RAG Architecture

## 1. Objective

Build a production-ready Enterprise Knowledge Assistant that enables authenticated users to search, chat with, and retrieve grounded answers from enterprise knowledge sources. The system should support secure multi-tenant document ingestion, hybrid retrieval, citation-backed responses, and operational readiness from the first implementation phase.

## 2. Core Technology Stack

- Frontend: Next.js
- Backend API: FastAPI
- Primary database: PostgreSQL
- Vector search: pgvector
- Cache and queue support: Redis
- Local orchestration: Docker Compose

## 3. High-Level Architecture

```text
+--------------------+        +--------------------+
|    Next.js UI      | <----> |   FastAPI API      |
| chat, admin, auth  |        | auth, chat, ingest |
+--------------------+        +--------------------+
                                        |
                +-----------------------+------------------------+
                |                        |                       |
                v                        v                       v
         +-------------+         +---------------+        +-------------+
         | PostgreSQL  |         |   pgvector    |        |    Redis    |
         | metadata    |         | embeddings    |        | cache/queue |
         +-------------+         +---------------+        +-------------+
                ^
                |
        +------------------+
        | Ingestion Worker |
        | parse/chunk/embed|
        +------------------+
```

## 4. Functional Domains

### 4.1 User Experience

- Conversational Q&A with citations
- Search across indexed enterprise knowledge
- Source previews and document references
- Admin surfaces for sources, jobs, users, and observability

### 4.2 Backend Domains

- Identity and access control
- Knowledge source registration
- Ingestion pipeline orchestration
- Document chunking and embedding
- Retrieval and reranking
- Answer generation with grounding
- Audit logging and observability

## 5. Request and Data Flows

### 5.1 Ingestion Flow

1. Admin registers a source or uploads content.
2. FastAPI stores source metadata in PostgreSQL.
3. An ingestion job is enqueued in Redis.
4. Worker fetches content, normalizes it, and extracts text.
5. Content is chunked with metadata boundaries preserved.
6. Embeddings are generated and stored in PostgreSQL with pgvector.
7. Job status, metrics, and errors are persisted.

### 5.2 Retrieval and Chat Flow

1. User sends a chat query from the Next.js frontend.
2. FastAPI authenticates and resolves tenant/workspace scope.
3. Query is rewritten or expanded if enabled.
4. Retrieval executes against:
   - vector similarity over chunks
   - metadata filters
   - optional lexical or exact-match fallback
5. Retrieved chunks are reranked and deduplicated.
6. Prompt assembly injects only allowed context.
7. Answer is generated with citations.
8. Conversation turn, sources used, and latency metrics are recorded.

## 6. Logical Components

### 6.1 Next.js Frontend

- Chat workspace
- Search results and source viewer
- Admin console
- Auth/session management
- Streaming response UI

### 6.2 FastAPI Services

- `api`: HTTP routes and versioned contracts
- `auth`: identity, RBAC, tenant resolution
- `chat`: conversations, responses, citations
- `retrieval`: query preparation, recall, reranking
- `ingestion`: source lifecycle, jobs, parsing orchestration
- `admin`: health, metrics views, source/job controls

### 6.3 Worker Layer

- Asynchronous ingestion jobs
- Re-embedding or reindex operations
- Scheduled syncs for connectors
- Retry and dead-letter handling

### 6.4 Storage Layer

- PostgreSQL for relational data and audit history
- pgvector for embedding storage and nearest-neighbor search
- Redis for short-lived caching, rate limit counters, and queues

## 7. Multi-Tenancy and Isolation

Recommended initial model:

- Single PostgreSQL cluster
- Shared schema with tenant-scoped rows
- Mandatory tenant filtering in all application queries
- Role-based access control layered on tenant boundaries

Future upgrade path:

- Per-tenant schema or database for strict isolation tenants
- Dedicated embedding partitions for large enterprise accounts

## 8. Security Architecture

- SSO/OIDC-compatible authentication boundary
- RBAC roles: `platform_admin`, `tenant_admin`, `editor`, `viewer`
- All records include tenant ownership
- Source access enforced at retrieval time, not only UI time
- Encrypted secrets for connector credentials
- Audit trail for uploads, deletions, searches, and chat access
- PII-aware logging policy with prompt/content redaction controls

## 9. Retrieval Strategy

Recommended baseline:

- Dense vector retrieval over document chunks
- Metadata filters by tenant, workspace, source, classification, and status
- Recency and source-priority weighting
- Lightweight reranking stage before answer generation
- Strict citation packaging with chunk and document identifiers

Recommended future extensions:

- Hybrid BM25 + vector retrieval
- Query expansion and synonym support
- Semantic caching for repeated questions
- Knowledge graph augmentation for structured sources

## 10. Data Model Overview

Primary entities:

- tenants
- users
- roles and memberships
- knowledge_sources
- source_sync_jobs
- documents
- document_versions
- document_chunks
- embeddings
- conversations
- messages
- citations
- audit_logs

Detailed schema is defined in `docs/DATABASE_SCHEMA.md`.

## 11. Deployment Topology

### Local and Integration Environments

Docker Compose services:

- `frontend`
- `backend`
- `postgres`
- `redis`
- `worker`

### Production Reference Topology

- Stateless Next.js service
- Stateless FastAPI API service
- Separate worker deployment
- Managed PostgreSQL with pgvector enabled
- Managed Redis
- Reverse proxy / ingress with TLS termination
- Centralized logging and metrics backend

## 12. Operational Concerns

- Health endpoints for API, DB, Redis, and worker dependencies
- Structured JSON logging
- Metrics for ingestion latency, retrieval latency, answer latency, token use, cache hit rate
- Distributed tracing across API and worker flows
- Backpressure controls for ingestion jobs
- Retry policies with idempotent job execution

## 13. Scalability Approach

- Scale frontend and backend horizontally
- Scale workers independently from request-serving API
- Partition embeddings and documents by tenant and source
- Use pgvector index tuning per embedding size and volume
- Cache repeated retrieval metadata and auth resolution in Redis

## 14. Non-Functional Requirements

- Tenant-safe authorization on every request path
- Citation-backed responses only
- Deterministic ingestion status tracking
- Observability and auditability from day one
- Clear separation between request-serving and background workloads

## 15. Initial Repository Structure

```text
rag-project/
  .github/
    workflows/
  backend/
    app/
      api/
        v1/
          endpoints/
      core/
      db/
      ingestion/
      models/
      observability/
      repositories/
      retrieval/
      schemas/
      services/
      workers/
    tests/
      integration/
      unit/
  docs/
  frontend/
    public/
    src/
      app/
      components/
      features/
        admin/
        chat/
      hooks/
      lib/
  infra/
    db/
      init/
      migrations/
    docker/
    redis/
  scripts/
```

## 16. Initial Delivery Boundary

This phase should create only:

- architecture and design documentation
- API and schema specifications
- implementation plan
- repository folder skeleton

This phase should not yet implement:

- business logic
- UI screens
- auth integration
- ingestion parsers
- embedding generation
- chat orchestration
