from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import reset_settings_cache
from app.db.session import create_database_schema, get_session_factory, reset_database_state
from app.main import create_app
from app.models.document import Document, DocumentChunk
from app.models.source import SourceSyncJob


class IngestionPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = TemporaryDirectory()
        self._base_path = Path(self._tmpdir.name)

    def tearDown(self) -> None:
        reset_database_state()
        reset_settings_cache()
        self._tmpdir.cleanup()

    def test_upload_persists_storage_chunks_and_completed_status(self) -> None:
        with self._client() as client:
            response = client.post(
                "/api/v1/documents/upload",
                files={"file": ("handbook.txt", b"hello world\n\nthis is a policy", "text/plain")},
            )

            self.assertEqual(response.status_code, 202)
            payload = response.json()["data"]
            self.assertEqual(payload["filename"], "handbook.txt")
            self.assertEqual(payload["status"], "completed")
            self.assertIsNone(payload["error_message"])

            document_id = payload["document_id"]
            status_response = client.get(f"/api/v1/documents/{document_id}/status")
            self.assertEqual(status_response.status_code, 200)
            status_payload = status_response.json()["data"]
            self.assertEqual(status_payload["status"], "completed")
            self.assertEqual(status_payload["processing_attempts"], 1)
            self.assertIsNotNone(status_payload["processed_at"])

            with get_session_factory()() as db:
                document = db.get(Document, uuid.UUID(document_id))
                self.assertIsNotNone(document)
                assert document is not None
                self.assertEqual(document.status, "completed")
                self.assertEqual(document.storage_backend, "local")
                self.assertTrue(document.storage_path)
                self.assertGreater(document.file_size_bytes or 0, 0)
                self.assertTrue(document.checksum_sha256)
                self.assertEqual(document.metadata_json["chunk_count"], 1)
                stored_path = self._uploads_path() / document.storage_path
                self.assertTrue(stored_path.exists())
                self.assertEqual(stored_path.read_text(), "hello world\n\nthis is a policy")

                chunks = db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document.id)).all()
                self.assertEqual(len(chunks), 1)
                self.assertIn("hello world", chunks[0].content)

    def test_failed_upload_surfaces_error_status(self) -> None:
        with self._client() as client:
            response = client.post(
                "/api/v1/documents/upload",
                files={"file": ("archive.bin", b"\x00\x01\x02", "application/octet-stream")},
            )

            self.assertEqual(response.status_code, 202)
            payload = response.json()["data"]
            self.assertEqual(payload["status"], "failed")
            self.assertIn("Unsupported file type", payload["error_message"])

            document_id = payload["document_id"]
            status_response = client.get(f"/api/v1/documents/{document_id}/status")
            status_payload = status_response.json()["data"]
            self.assertEqual(status_payload["status"], "failed")
            self.assertEqual(status_payload["processing_attempts"], 1)
            self.assertIsNone(status_payload["processed_at"])

    def test_background_mode_returns_queued_then_completes(self) -> None:
        with self._client(mode="background") as client:
            response = client.post(
                "/api/v1/documents/upload",
                files={"file": ("policy.txt", b"PTO carryover policy allows forty hours.", "text/plain")},
            )

            self.assertEqual(response.status_code, 202)
            payload = response.json()["data"]
            self.assertEqual(payload["status"], "queued")

            status_response = client.get(f"/api/v1/documents/{payload['document_id']}/status")
            status_payload = status_response.json()["data"]
            self.assertEqual(status_payload["status"], "completed")
            self.assertEqual(status_payload["processing_attempts"], 1)

    def test_source_sync_reprocesses_existing_source_documents(self) -> None:
        with self._client() as client:
            create_source = client.post(
                "/api/v1/sources",
                json={"name": "Engineering Handbook", "type": "upload", "classification": "internal"},
            )
            source_id = create_source.json()["data"]["id"]

            upload = client.post(
                f"/api/v1/sources/{source_id}/upload",
                files={"file": ("handbook.txt", b"Original policy text.", "text/plain")},
            )
            self.assertEqual(upload.status_code, 202)
            document_id = upload.json()["data"]["document_id"]

            with get_session_factory()() as db:
                document = db.get(Document, uuid.UUID(document_id))
                assert document is not None
                stored_path = self._uploads_path() / document.storage_path
                stored_path.write_text("Updated policy text after sync.", encoding="utf-8")

            sync_response = client.post(f"/api/v1/sources/{source_id}/sync")
            self.assertEqual(sync_response.status_code, 202)
            job_id = sync_response.json()["data"]["job_id"]

            with get_session_factory()() as db:
                job = db.get(SourceSyncJob, uuid.UUID(job_id))
                document = db.get(Document, uuid.UUID(document_id))
                assert job is not None
                assert document is not None
                self.assertEqual(job.status, "completed")
                self.assertEqual(job.documents_total, 1)
                self.assertEqual(job.documents_processed, 1)
                self.assertEqual(job.documents_failed, 0)
                self.assertEqual(document.status, "completed")
                self.assertEqual(document.processing_attempts, 2)

                chunks = db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document.id)).all()
                self.assertEqual(len(chunks), 1)
                self.assertIn("Updated policy text after sync.", chunks[0].content)

    def test_source_sync_marks_job_and_document_failed_when_file_is_missing(self) -> None:
        with self._client() as client:
            create_source = client.post(
                "/api/v1/sources",
                json={"name": "Retention Policy", "type": "upload", "classification": "internal"},
            )
            source_id = create_source.json()["data"]["id"]

            upload = client.post(
                f"/api/v1/sources/{source_id}/upload",
                files={"file": ("retention.txt", b"Retention periods are documented here.", "text/plain")},
            )
            document_id = upload.json()["data"]["document_id"]

            with get_session_factory()() as db:
                document = db.get(Document, uuid.UUID(document_id))
                assert document is not None
                stored_path = self._uploads_path() / document.storage_path
                stored_path.unlink()

            sync_response = client.post(f"/api/v1/sources/{source_id}/sync")
            self.assertEqual(sync_response.status_code, 202)
            job_id = sync_response.json()["data"]["job_id"]

            with get_session_factory()() as db:
                job = db.get(SourceSyncJob, uuid.UUID(job_id))
                document = db.get(Document, uuid.UUID(document_id))
                assert job is not None
                assert document is not None
                self.assertEqual(job.status, "failed")
                self.assertEqual(job.documents_total, 1)
                self.assertEqual(job.documents_processed, 1)
                self.assertEqual(job.documents_failed, 1)
                self.assertIn("failed during sync", job.error_message or "")
                self.assertEqual(document.status, "failed")
                self.assertIn("Stored upload is missing", document.processing_error or "")
                self.assertEqual(document.processing_attempts, 2)

    def _client(self, mode: str = "inline") -> TestClient:
        database_path = self._base_path / "test.db"
        uploads_path = self._uploads_path()
        os.environ["APP_DATABASE_URL"] = f"sqlite+pysqlite:///{database_path}"
        os.environ["APP_AUTO_CREATE_TABLES"] = "true"
        os.environ["APP_UPLOADS_DIR"] = str(uploads_path)
        os.environ["APP_INGESTION_EXECUTION_MODE"] = mode

        reset_settings_cache()
        reset_database_state()

        app = create_app()
        create_database_schema()
        return TestClient(app)

    def _uploads_path(self) -> Path:
        return self._base_path / "uploads"


if __name__ == "__main__":
    unittest.main()
