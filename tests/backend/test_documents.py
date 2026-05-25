import logging


def test_document_upload_processes_and_completes_synchronously(client, caplog):
    caplog.set_level(logging.INFO)
    upload_response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("handbook.txt", b"hello world\n\nthis is a policy", "text/plain")},
    )

    assert upload_response.status_code == 202
    upload_body = upload_response.json()
    assert upload_body["data"]["filename"] == "handbook.txt"
    assert upload_body["data"]["status"] == "completed"
    assert upload_body["data"]["error_message"] is None

    document_id = upload_body["data"]["document_id"]
    status_response = client.get(f"/api/v1/documents/{document_id}/status")

    assert status_response.status_code == 200
    status_body = status_response.json()
    assert status_body["data"]["document_id"] == document_id
    assert status_body["data"]["status"] == "completed"
    assert status_body["data"]["error_message"] is None

    list_response = client.get("/api/v1/documents")
    assert list_response.status_code == 200
    assert list_response.json()["data"][0]["status"] == "completed"

    messages = [record.message for record in caplog.records]
    assert "document uploaded" in messages
    assert "document processing started" in messages
    assert "document processing completed" in messages


def test_pdf_upload_processes_successfully(client):
    upload_response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("handbook.pdf", _sample_pdf_bytes("Retention policy"), "application/pdf")},
    )

    assert upload_response.status_code == 202
    upload_body = upload_response.json()
    assert upload_body["data"]["status"] == "completed"
    assert upload_body["data"]["error_message"] is None

    document_id = upload_body["data"]["document_id"]
    status_response = client.get(f"/api/v1/documents/{document_id}/status")
    assert status_response.status_code == 200
    assert status_response.json()["data"]["status"] == "completed"


def test_document_upload_sets_failed_status_and_error_message_on_processing_error(client):
    upload_response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("archive.bin", b"\x00\x01\x02", "application/octet-stream")},
    )

    assert upload_response.status_code == 202
    upload_body = upload_response.json()
    assert upload_body["data"]["status"] == "failed"
    assert upload_body["data"]["error_message"]

    document_id = upload_body["data"]["document_id"]
    status_response = client.get(f"/api/v1/documents/{document_id}/status")
    assert status_response.status_code == 200
    status_body = status_response.json()
    assert status_body["data"]["status"] == "failed"
    assert "Unsupported file type" in status_body["data"]["error_message"]


def test_document_status_returns_not_found_for_unknown_id(client):
    response = client.get("/api/v1/documents/00000000-0000-0000-0000-000000000000/status")

    assert response.status_code == 404


def _sample_pdf_bytes(text: str) -> bytes:
    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        (
            b"3 0 obj\n"
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>\n"
            b"endobj\n"
        ),
        (
            b"4 0 obj\n"
            + f"<< /Length {len(_pdf_stream(text))} >>\nstream\n".encode("utf-8")
            + _pdf_stream(text)
            + b"\nendstream\nendobj\n"
        ),
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    ]

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(pdf))
        pdf.extend(obj)

    xref_start = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("utf-8"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("utf-8"))
    pdf.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_start}\n%%EOF\n"
        ).encode("utf-8")
    )
    return bytes(pdf)


def _pdf_stream(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return f"BT\n/F1 18 Tf\n72 72 Td\n({escaped}) Tj\nET".encode("utf-8")
