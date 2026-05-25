from app.db.session import get_session_factory
from app.models.document import Document, DocumentChunk, DocumentChunkEmbedding
from app.services.ingestion import LocalDocumentIngestionService


def test_search_endpoint_returns_grounded_results_with_citations(client):
    upload_response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("handbook.txt", b"PTO carryover policy allows forty hours of unused vacation.", "text/plain")},
    )
    assert upload_response.status_code == 202
    assert upload_response.json()["data"]["status"] == "completed"

    response = client.post(
        "/api/v1/search",
        json={"query": "pto carryover", "top_k": 5, "filters": {"source_ids": []}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["results"]
    result = body["data"]["results"][0]
    assert result["document_title"] == "handbook.txt"
    assert result["snippet"]
    assert result["citation"]["title"] == "handbook.txt"
    assert result["citation"]["chunk_id"] == result["chunk_id"]


def test_completed_documents_persist_chunk_embeddings_for_search(client):
    upload_response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("handbook.txt", b"PTO carryover policy allows forty hours of unused vacation.", "text/plain")},
    )
    assert upload_response.status_code == 202

    with get_session_factory()() as db:
        stored_embeddings = db.query(DocumentChunkEmbedding).all()
        assert stored_embeddings
        assert stored_embeddings[0].embedding_model == "local-hashing-v1"
        assert stored_embeddings[0].embedding_dimension == 256
        assert len(stored_embeddings[0].embedding_json) == 256
        before_count = len(stored_embeddings)

    first_response = client.post(
        "/api/v1/search",
        json={"query": "pto carryover", "top_k": 5, "filters": {"source_ids": []}},
    )
    second_response = client.post(
        "/api/v1/search",
        json={"query": "pto carryover", "top_k": 5, "filters": {"source_ids": []}},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.json()["data"]["results"][0]["chunk_id"] == second_response.json()["data"]["results"][0]["chunk_id"]

    with get_session_factory()() as db:
        after_count = db.query(DocumentChunkEmbedding).count()
        assert after_count == before_count


def test_document_reprocessing_replaces_old_chunk_embeddings(client):
    upload_response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("handbook.txt", b"PTO carryover policy allows forty hours of unused vacation.", "text/plain")},
    )
    assert upload_response.status_code == 202
    document_id = upload_response.json()["data"]["document_id"]

    with get_session_factory()() as db:
        original_chunk_ids = {str(chunk_id) for (chunk_id,) in db.query(DocumentChunk.id).all()}
        original_embedding_ids = {str(chunk_id) for (chunk_id,) in db.query(DocumentChunkEmbedding.chunk_id).all()}
        assert original_chunk_ids
        assert original_chunk_ids == original_embedding_ids

    LocalDocumentIngestionService().process_document(document_id)

    with get_session_factory()() as db:
        document_count = db.query(Document).count()
        replacement_chunk_ids = {str(chunk_id) for (chunk_id,) in db.query(DocumentChunk.id).all()}
        replacement_embedding_ids = {str(chunk_id) for (chunk_id,) in db.query(DocumentChunkEmbedding.chunk_id).all()}
        assert document_count == 1
        assert replacement_chunk_ids
        assert replacement_chunk_ids == replacement_embedding_ids
        assert replacement_chunk_ids.isdisjoint(original_chunk_ids)


def test_search_ranks_relevant_completed_documents_across_multiple_uploads(client):
    upload_a = client.post(
        "/api/v1/documents/upload",
        files={"file": ("pto-policy.txt", b"PTO carryover policy allows forty hours of unused vacation for full-time employees.", "text/plain")},
    )
    upload_b = client.post(
        "/api/v1/documents/upload",
        files={"file": ("security.txt", b"Security policy requires hardware keys and quarterly access review.", "text/plain")},
    )
    upload_c = client.post(
        "/api/v1/documents/upload",
        files={"file": ("benefits.txt", b"Benefits enrollment opens every November and explains payroll deductions.", "text/plain")},
    )
    assert upload_a.status_code == 202
    assert upload_b.status_code == 202
    assert upload_c.status_code == 202

    response = client.post(
        "/api/v1/search",
        json={"query": "pto carryover vacation policy", "top_k": 3, "filters": {"source_ids": []}},
    )

    assert response.status_code == 200
    results = response.json()["data"]["results"]
    assert len(results) >= 2
    assert results[0]["document_title"] == "pto-policy.txt"
    assert results[0]["citation"]["title"] == "pto-policy.txt"
    assert results[0]["citation"]["chunk_id"] == results[0]["chunk_id"]


def test_search_preserves_filters_with_persisted_embeddings(client):
    source_a = client.post(
        "/api/v1/sources",
        json={"name": "Policies", "type": "upload", "classification": "internal"},
    ).json()["data"]["id"]
    source_b = client.post(
        "/api/v1/sources",
        json={"name": "Security", "type": "upload", "classification": "internal"},
    ).json()["data"]["id"]

    upload_a = client.post(
        f"/api/v1/sources/{source_a}/upload",
        files={"file": ("pto-policy.txt", b"PTO carryover policy allows forty hours of unused vacation.", "text/plain")},
    )
    upload_b = client.post(
        f"/api/v1/sources/{source_b}/upload",
        files={"file": ("security-policy.txt", b"Security policy requires hardware keys.", "text/plain")},
    )
    assert upload_a.status_code == 202
    assert upload_b.status_code == 202

    response = client.post(
        "/api/v1/search",
        json={"query": "policy", "top_k": 5, "filters": {"source_ids": [source_a]}},
    )

    assert response.status_code == 200
    results = response.json()["data"]["results"]
    assert results
    assert {result["source_id"] for result in results} == {source_a}
    assert {result["citation"]["title"] for result in results} == {"pto-policy.txt"}
