# Enterprise Knowledge Assistant Database Schema

## 1. Goals

- Support multi-tenant enterprise knowledge management
- Keep document metadata relational and queryable
- Store embeddings in PostgreSQL with pgvector
- Preserve auditability across ingestion and chat flows
- Allow incremental expansion without immediate repartitioning

## 2. Extensions

Required PostgreSQL extensions:

- `uuid-ossp` or equivalent UUID generation
- `vector`

## 3. Schema Conventions

- Primary keys use UUID
- All primary business tables include `created_at` and `updated_at`
- Soft-delete where recovery or auditability matters
- Tenant-owned tables include `tenant_id`
- Large text content stays in version and chunk tables, not parent entities

## 4. Core Tables

### 4.1 `tenants`

| Column | Type | Notes |
|---|---|---|
| id | uuid pk | tenant identifier |
| name | varchar(255) | display name |
| slug | varchar(100) unique | URL-safe tenant key |
| status | varchar(50) | active, suspended |
| created_at | timestamptz | audit |
| updated_at | timestamptz | audit |

### 4.2 `users`

| Column | Type | Notes |
|---|---|---|
| id | uuid pk | internal user identifier |
| external_auth_id | varchar(255) unique | OIDC subject or provider ID |
| email | varchar(320) | normalized email |
| display_name | varchar(255) | user name |
| status | varchar(50) | active, disabled |
| created_at | timestamptz | audit |
| updated_at | timestamptz | audit |

### 4.3 `tenant_memberships`

| Column | Type | Notes |
|---|---|---|
| id | uuid pk | membership row |
| tenant_id | uuid fk | references tenants |
| user_id | uuid fk | references users |
| role | varchar(50) | platform_admin, tenant_admin, editor, viewer |
| created_at | timestamptz | audit |
| updated_at | timestamptz | audit |

Unique constraint:

- `(tenant_id, user_id)`

### 4.4 `workspaces`

Optional but recommended tenant subdivision for departments, teams, or business units.

| Column | Type | Notes |
|---|---|---|
| id | uuid pk | workspace identifier |
| tenant_id | uuid fk | tenant owner |
| name | varchar(255) | display name |
| slug | varchar(100) | workspace key |
| created_at | timestamptz | audit |
| updated_at | timestamptz | audit |

Unique constraint:

- `(tenant_id, slug)`

## 5. Source and Document Tables

### 5.1 `knowledge_sources`

| Column | Type | Notes |
|---|---|---|
| id | uuid pk | source identifier |
| tenant_id | uuid fk | tenant owner |
| workspace_id | uuid fk nullable | workspace scope |
| name | varchar(255) | source name |
| source_type | varchar(50) | upload, drive, wiki, web, api |
| status | varchar(50) | active, paused, deleted |
| classification | varchar(50) | public, internal, confidential |
| config_json | jsonb | connector config sans secrets |
| created_by | uuid fk | creator |
| created_at | timestamptz | audit |
| updated_at | timestamptz | audit |
| deleted_at | timestamptz nullable | soft delete |

Indexes:

- `(tenant_id, workspace_id, status)`
- `(tenant_id, source_type)`

### 5.2 `source_sync_jobs`

| Column | Type | Notes |
|---|---|---|
| id | uuid pk | job identifier |
| tenant_id | uuid fk | tenant owner |
| source_id | uuid fk | source |
| job_type | varchar(50) | ingest, sync, reindex, delete |
| status | varchar(50) | queued, running, succeeded, failed |
| triggered_by | uuid fk nullable | initiator |
| started_at | timestamptz nullable | execution start |
| finished_at | timestamptz nullable | execution end |
| metrics_json | jsonb | counts and timings |
| error_json | jsonb nullable | failure summary |
| created_at | timestamptz | audit |
| updated_at | timestamptz | audit |

Indexes:

- `(tenant_id, source_id, status)`
- `(tenant_id, created_at desc)`

### 5.3 `documents`

| Column | Type | Notes |
|---|---|---|
| id | uuid pk | document identifier |
| tenant_id | uuid fk | tenant owner |
| workspace_id | uuid fk nullable | workspace scope |
| source_id | uuid fk | parent source |
| external_document_id | varchar(255) nullable | connector-native ID |
| title | varchar(512) | document title |
| document_type | varchar(100) nullable | policy, guide, wiki, pdf |
| mime_type | varchar(255) nullable | content type |
| status | varchar(50) | active, superseded, deleted |
| latest_version_id | uuid nullable | pointer for convenience |
| metadata_json | jsonb | arbitrary metadata |
| created_at | timestamptz | audit |
| updated_at | timestamptz | audit |
| deleted_at | timestamptz nullable | soft delete |

Indexes:

- `(tenant_id, source_id, status)`
- `(tenant_id, workspace_id)`
- `(tenant_id, external_document_id)`

### 5.4 `document_versions`

| Column | Type | Notes |
|---|---|---|
| id | uuid pk | version identifier |
| tenant_id | uuid fk | tenant owner |
| document_id | uuid fk | parent document |
| version_number | integer | monotonic version |
| content_hash | varchar(128) | dedupe and change tracking |
| storage_uri | text nullable | object storage path if introduced later |
| extracted_text | text | normalized full text |
| parser_name | varchar(100) nullable | parser used |
| token_count | integer nullable | prompt planning |
| created_at | timestamptz | audit |
| updated_at | timestamptz | audit |

Unique constraint:

- `(document_id, version_number)`

Indexes:

- `(tenant_id, document_id)`
- `(tenant_id, content_hash)`

### 5.5 `document_chunks`

| Column | Type | Notes |
|---|---|---|
| id | uuid pk | chunk identifier |
| tenant_id | uuid fk | tenant owner |
| document_id | uuid fk | parent document |
| document_version_id | uuid fk | source version |
| chunk_index | integer | stable order within version |
| content | text | chunk text |
| token_count | integer nullable | chunk size |
| section_title | varchar(255) nullable | semantic grouping |
| page_number | integer nullable | for PDFs |
| metadata_json | jsonb | chunk metadata |
| created_at | timestamptz | audit |
| updated_at | timestamptz | audit |

Unique constraint:

- `(document_version_id, chunk_index)`

Indexes:

- `(tenant_id, document_id)`
- `(tenant_id, document_version_id)`

### 5.6 `chunk_embeddings`

| Column | Type | Notes |
|---|---|---|
| id | uuid pk | embedding identifier |
| tenant_id | uuid fk | tenant owner |
| chunk_id | uuid fk unique | one active embedding per chunk per model in baseline design |
| embedding_model | varchar(100) | model identifier |
| embedding | vector(1536) | dimension depends on model choice |
| created_at | timestamptz | audit |

Indexes:

- ivfflat or hnsw index on `embedding`
- btree on `(tenant_id, embedding_model)`

Note:

- If multiple embeddings per chunk are needed later, replace unique `chunk_id` with unique `(chunk_id, embedding_model)`.

## 6. Chat and Retrieval Tables

### 6.1 `conversations`

| Column | Type | Notes |
|---|---|---|
| id | uuid pk | conversation identifier |
| tenant_id | uuid fk | tenant owner |
| workspace_id | uuid fk nullable | workspace scope |
| user_id | uuid fk | owner |
| title | varchar(255) nullable | derived summary |
| status | varchar(50) | active, archived |
| created_at | timestamptz | audit |
| updated_at | timestamptz | audit |

Indexes:

- `(tenant_id, user_id, updated_at desc)`

### 6.2 `messages`

| Column | Type | Notes |
|---|---|---|
| id | uuid pk | message identifier |
| tenant_id | uuid fk | tenant owner |
| conversation_id | uuid fk | parent conversation |
| role | varchar(20) | user, assistant, system |
| content | text | message text |
| model_name | varchar(100) nullable | for assistant messages |
| prompt_tokens | integer nullable | usage |
| completion_tokens | integer nullable | usage |
| latency_ms | integer nullable | generation latency |
| created_at | timestamptz | audit |

Indexes:

- `(tenant_id, conversation_id, created_at)`

### 6.3 `message_citations`

| Column | Type | Notes |
|---|---|---|
| id | uuid pk | citation row |
| tenant_id | uuid fk | tenant owner |
| message_id | uuid fk | assistant message |
| document_id | uuid fk | cited document |
| chunk_id | uuid fk | cited chunk |
| citation_label | varchar(100) nullable | page, section, anchor |
| rank | integer | display order |
| created_at | timestamptz | audit |

Indexes:

- `(tenant_id, message_id)`

### 6.4 `search_queries`

Optional analytics table for search observability.

| Column | Type | Notes |
|---|---|---|
| id | uuid pk | query record |
| tenant_id | uuid fk | tenant owner |
| user_id | uuid fk | initiator |
| query_text | text | raw query |
| filters_json | jsonb | applied filters |
| top_k | integer | requested recall |
| latency_ms | integer nullable | execution latency |
| created_at | timestamptz | audit |

## 7. Audit and Secret-Adjacents

### 7.1 `audit_logs`

| Column | Type | Notes |
|---|---|---|
| id | uuid pk | audit event |
| tenant_id | uuid fk nullable | tenant context |
| user_id | uuid fk nullable | actor |
| action | varchar(100) | create_source, search, delete_document |
| target_type | varchar(100) | source, document, conversation |
| target_id | uuid nullable | target row |
| payload_json | jsonb | sanitized event data |
| created_at | timestamptz | audit |

Indexes:

- `(tenant_id, created_at desc)`
- `(user_id, created_at desc)`

### 7.2 `source_credentials`

If stored in database, keep encrypted and access-restricted. Alternative is external secret manager.

| Column | Type | Notes |
|---|---|---|
| id | uuid pk | credential row |
| tenant_id | uuid fk | tenant owner |
| source_id | uuid fk | source |
| secret_ref | varchar(255) | external secret reference preferred |
| created_at | timestamptz | audit |
| updated_at | timestamptz | audit |

## 8. Recommended Indexing Strategy

- Relational filters first: tenant, workspace, source, status
- pgvector ANN index on `chunk_embeddings.embedding`
- Btree indexes on common admin and job-list filters
- GIN indexes on selected `jsonb` metadata fields if query patterns justify them

## 9. Deletion Strategy

- Soft-delete sources and documents
- Hard-delete embeddings and chunks only in controlled cleanup jobs
- Preserve audit logs
- Use cascading behavior carefully; prefer application-driven cleanup for traceability

## 10. Migration Strategy

- Use versioned SQL migrations from day one
- Enable pgvector in base migration
- Create relational tables before embedding indexes
- Backfill `latest_version_id` after version inserts if needed

## 11. Future Extensions

- ACL table for document-level permissions
- Connector sync cursors table
- Feedback tables for answer quality
- Prompt template registry
- Semantic cache tables
- Per-tenant embedding model overrides
