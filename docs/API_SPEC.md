# Enterprise Knowledge Assistant API Specification

## 1. Principles

- Version all HTTP APIs under `/api/v1`
- Keep frontend-to-backend contracts JSON-first
- Support SSE or streaming HTTP for chat responses in later phases
- Enforce tenant and role authorization at API boundaries
- Use asynchronous jobs for ingestion and synchronization workflows

## 2. Authentication and Headers

### Required Headers

- `Authorization: Bearer <token>`
- `X-Tenant-Id: <tenant_id>` for internal or admin-scoped requests when applicable
- `X-Request-Id: <uuid>` optional but recommended

### Auth Model

- External identity provider via OIDC/SSO
- Backend validates token and resolves user + tenant memberships
- Role checks enforced in route dependencies

## 3. Common Response Envelope

Success:

```json
{
  "data": {},
  "meta": {
    "request_id": "uuid"
  }
}
```

Error:

```json
{
  "error": {
    "code": "RESOURCE_NOT_FOUND",
    "message": "Document not found",
    "details": {}
  },
  "meta": {
    "request_id": "uuid"
  }
}
```

## 4. Health and System Endpoints

### `GET /api/v1/health`

Purpose:
- Liveness/readiness summary

Response:

```json
{
  "data": {
    "status": "ok",
    "services": {
      "api": "ok",
      "postgres": "ok",
      "redis": "ok"
    }
  }
}
```

## 5. Tenant and User Endpoints

### `GET /api/v1/me`

Purpose:
- Resolve current user profile, memberships, and effective roles

### `GET /api/v1/tenants`

Purpose:
- List visible tenants for current user

Authorization:
- authenticated user

## 6. Source Management Endpoints

### `GET /api/v1/sources`

Purpose:
- List knowledge sources in current tenant

Query params:
- `status`
- `type`
- `workspace_id`
- `page`
- `page_size`

### `POST /api/v1/sources`

Purpose:
- Register a source definition

Request body:

```json
{
  "name": "Engineering Handbook",
  "type": "upload",
  "workspace_id": "uuid",
  "config": {
    "path": "/imports/engineering-handbook.pdf"
  },
  "classification": "internal"
}
```

### `GET /api/v1/sources/{source_id}`

Purpose:
- Fetch source details

### `PATCH /api/v1/sources/{source_id}`

Purpose:
- Update mutable source metadata

### `DELETE /api/v1/sources/{source_id}`

Purpose:
- Soft delete a source and mark related documents inactive

## 7. Upload and Ingestion Endpoints

### `POST /api/v1/sources/{source_id}/upload`

Purpose:
- Upload a file for a source

Notes:
- Multipart endpoint
- Returns accepted upload metadata

### `POST /api/v1/sources/{source_id}/sync`

Purpose:
- Trigger sync or reindex

Response:

```json
{
  "data": {
    "job_id": "uuid",
    "status": "queued"
  }
}
```

### `GET /api/v1/jobs`

Purpose:
- List ingestion and sync jobs

### `GET /api/v1/jobs/{job_id}`

Purpose:
- Fetch job status, timestamps, counters, and error summary

## 8. Search Endpoints

### `POST /api/v1/search`

Purpose:
- Run grounded semantic search without generating an answer

Request body:

```json
{
  "query": "What is the PTO carryover policy?",
  "workspace_id": "uuid",
  "filters": {
    "source_ids": ["uuid"],
    "document_types": ["policy"],
    "classification": ["internal"]
  },
  "top_k": 10
}
```

Response:

```json
{
  "data": {
    "results": [
      {
        "chunk_id": "uuid",
        "document_id": "uuid",
        "document_title": "Employee Handbook",
        "score": 0.91,
        "snippet": "Unused PTO may be carried over...",
        "source_id": "uuid"
      }
    ]
  }
}
```

## 9. Conversation and Chat Endpoints

### `POST /api/v1/conversations`

Purpose:
- Create a conversation container

### `GET /api/v1/conversations`

Purpose:
- List recent conversations for current user

### `GET /api/v1/conversations/{conversation_id}`

Purpose:
- Fetch conversation metadata and messages

### `POST /api/v1/conversations/{conversation_id}/messages`

Purpose:
- Submit a user message and receive an assistant response

Request body:

```json
{
  "message": "Summarize the data retention policy.",
  "workspace_id": "uuid",
  "options": {
    "top_k": 8,
    "stream": false
  }
}
```

Response:

```json
{
  "data": {
    "message_id": "uuid",
    "role": "assistant",
    "content": "The retention policy states ...",
    "citations": [
      {
        "document_id": "uuid",
        "chunk_id": "uuid",
        "title": "Data Retention Policy",
        "locator": "Page 4"
      }
    ]
  }
}
```

### `POST /api/v1/conversations/{conversation_id}/messages/stream`

Purpose:
- Streaming variant for assistant generation

Transport:
- SSE or chunked HTTP

## 10. Document Endpoints

### `GET /api/v1/documents`

Purpose:
- List documents with filters

### `GET /api/v1/documents/{document_id}`

Purpose:
- Fetch document metadata and version summary

### `GET /api/v1/documents/{document_id}/chunks`

Purpose:
- Fetch chunk metadata for inspection and debugging

## 11. Admin and Audit Endpoints

### `GET /api/v1/admin/metrics`

Purpose:
- Operational metrics summary for dashboards

Authorization:
- `tenant_admin` or `platform_admin`

### `GET /api/v1/admin/audit-logs`

Purpose:
- Query audit trail events

## 12. Status Codes

- `200 OK` read success
- `201 Created` resource created
- `202 Accepted` async job queued
- `400 Bad Request` validation failure
- `401 Unauthorized` missing or invalid auth
- `403 Forbidden` authorization failure
- `404 Not Found` missing resource
- `409 Conflict` state conflict
- `422 Unprocessable Entity` schema validation failure
- `429 Too Many Requests` rate limit triggered
- `500 Internal Server Error` unhandled failure

## 13. Initial Pydantic Contract Families

Recommended schema groups:

- auth schemas
- tenant schemas
- source schemas
- job schemas
- search schemas
- conversation schemas
- message schemas
- document schemas
- audit schemas

## 14. API Boundaries for Phase 1

The first build phase should define route stubs and models for:

- health
- me
- sources
- jobs
- search
- conversations
- documents

The first build phase should not yet integrate:

- real SSO
- real connector sync
- real embeddings
- real answer generation
