def test_health_endpoint_reports_api_and_database(client):
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["status"] == "ok"
    assert body["data"]["services"]["api"] == "ok"
    assert body["data"]["services"]["postgres"] == "ok"
