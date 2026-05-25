def test_sources_conversations_and_documents_contracts(client):
    create_source = client.post(
        "/api/v1/sources",
        json={
            "name": "Engineering Handbook",
            "type": "upload",
            "classification": "internal",
        },
    )
    assert create_source.status_code == 201
    source_id = create_source.json()["data"]["id"]

    upload = client.post(
        f"/api/v1/sources/{source_id}/upload",
        files={"file": ("handbook.txt", b"hello world", "text/plain")},
    )
    assert upload.status_code == 202
    assert upload.json()["data"]["status"] == "completed"

    sync = client.post(f"/api/v1/sources/{source_id}/sync")
    assert sync.status_code == 202
    assert sync.json()["data"]["status"] == "queued"

    list_sources = client.get("/api/v1/sources")
    assert list_sources.status_code == 200
    assert list_sources.json()["data"][0]["id"] == source_id

    list_documents = client.get("/api/v1/documents")
    assert list_documents.status_code == 200
    assert list_documents.json()["data"][0]["source_id"] == source_id

    create_conversation = client.post("/api/v1/conversations", json={})
    assert create_conversation.status_code == 201
    conversation_id = create_conversation.json()["data"]["id"]

    message = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"message": "Summarize the policy."},
    )
    assert message.status_code == 200
    assert message.json()["data"]["role"] == "assistant"
    assert message.json()["data"]["citations"]

    conversation = client.get(f"/api/v1/conversations/{conversation_id}")
    assert conversation.status_code == 200
    assert len(conversation.json()["data"]["messages"]) == 2
    assert conversation.json()["data"]["messages"][1]["citations"]

    search = client.post("/api/v1/search", json={"query": "hello", "top_k": 5, "filters": {"source_ids": [source_id]}})
    assert search.status_code == 200
    assert search.json()["data"]["results"]
