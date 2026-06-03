import unittest
from types import SimpleNamespace

from backend.app.retrieval.hybrid import HybridRetriever, HybridScoringConfig
from backend.app.retrieval.interfaces import RetrievalQuery
from backend.app.retrieval.keyword_search import InMemoryKeywordSearch
from backend.app.retrieval.rerank import DeterministicReranker
from backend.app.retrieval.text import build_index_text
from backend.app.retrieval.storage import InMemoryPgVectorStore, PgVectorEmbeddingRecord
from backend.app.retrieval.vector_search import PgVectorSearch
from backend.app.services.document_models import SearchResult, SourceChunk
from backend.app.services.embeddings import HashingEmbeddingProvider, OpenAICompatibleEmbeddingProvider, TfidfEmbeddingProvider, get_embedding_provider


def _chunk(chunk_id: str, title: str, text: str, source_id: str = "source-a") -> SourceChunk:
    return SourceChunk(
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        document_version_id=f"ver-{chunk_id}",
        chunk_index=0,
        text=text,
        source_id=source_id,
        tenant_id="tenant-1",
        document_title=title,
        metadata={"classification": "internal"},
    )


def _result(chunk: SourceChunk, score: float) -> SearchResult:
    return SearchResult(chunk=chunk, score=score, vector_score=score, keyword_score=score, rank=1)


class RetrievalTests(unittest.TestCase):
    def test_vector_search_respects_filters_and_returns_citations(self) -> None:
        provider = TfidfEmbeddingProvider.fit(
            [
                "Employee Handbook PTO carryover policy allows forty hours.",
                "Security Guide Security policy requires annual review.",
            ]
        )
        store = InMemoryPgVectorStore()
        allowed_chunk = _chunk("chunk-1", "Employee Handbook", "PTO carryover policy allows forty hours.")
        filtered_chunk = _chunk("chunk-2", "Security Guide", "Security policy requires annual review.", "source-b")
        store.upsert_chunks([allowed_chunk, filtered_chunk])
        embeddings = provider.embed_texts([build_index_text(allowed_chunk), build_index_text(filtered_chunk)])
        store.upsert_embeddings(
            [
                PgVectorEmbeddingRecord(
                    chunk_id=allowed_chunk.chunk_id,
                    document_id=allowed_chunk.document_id,
                    embedding_model=provider.model_name,
                    embedding_dimension=provider.dimensions,
                    embedding=embeddings[0],
                ),
                PgVectorEmbeddingRecord(
                    chunk_id=filtered_chunk.chunk_id,
                    document_id=filtered_chunk.document_id,
                    embedding_model=provider.model_name,
                    embedding_dimension=provider.dimensions,
                    embedding=embeddings[1],
                ),
            ]
        )

        search = PgVectorSearch(store, provider)
        results = search.search(RetrievalQuery(text="pto carryover", top_k=5, filters={"source_id": "source-a"}))

        self.assertEqual([result.chunk.chunk_id for result in results], ["chunk-1"])
        self.assertEqual(results[0].to_payload()["citation"].title, "Employee Handbook")

    def test_hybrid_retrieval_fuses_vector_and_keyword_scores(self) -> None:
        chunk_a = _chunk("chunk-a", "Handbook", "PTO carryover policy allows forty hours of unused vacation.")
        chunk_b = _chunk("chunk-b", "Benefits FAQ", "Vacation carryover benefits are described in the general policy.")
        chunk_c = _chunk("chunk-c", "Security Guide", "Password rotation policy for privileged accounts.")
        chunks = [chunk_a, chunk_b, chunk_c]
        provider = TfidfEmbeddingProvider.fit([build_index_text(chunk) for chunk in chunks])
        store = InMemoryPgVectorStore()
        store.upsert_chunks(chunks)
        embeddings = provider.embed_texts([build_index_text(chunk) for chunk in chunks])
        store.upsert_embeddings(
            [
                PgVectorEmbeddingRecord(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    embedding_model=provider.model_name,
                    embedding_dimension=provider.dimensions,
                    embedding=embedding,
                )
                for chunk, embedding in zip(chunks, embeddings)
            ]
        )

        hybrid = HybridRetriever(
            vector_backend=PgVectorSearch(store, provider),
            keyword_backend=InMemoryKeywordSearch(chunks),
            config=HybridScoringConfig(vector_weight=0.7, keyword_weight=0.3, rrf_k=10),
        )

        results = hybrid.search(RetrievalQuery(text="pto carryover policy", top_k=3))

        self.assertEqual([result.chunk.chunk_id for result in results[:2]], ["chunk-a", "chunk-b"])
        self.assertIsNotNone(results[0].vector_score)
        self.assertIsNotNone(results[0].keyword_score)
        self.assertEqual(results[0].chunk.to_citation().locator, "Chunk 1")

    def test_hybrid_ranking_prefers_more_coherent_multi_term_match(self) -> None:
        chunk_a = _chunk("chunk-a", "PTO Policy", "PTO carryover policy allows employees to keep forty hours of vacation.")
        chunk_b = _chunk("chunk-b", "Benefits Notes", "Vacation policy describes enrollment windows and payroll deductions.")
        chunk_c = _chunk("chunk-c", "Carryover Memo", "Carryover exceptions require director approval for unused hours.")
        chunks = [chunk_a, chunk_b, chunk_c]
        provider = TfidfEmbeddingProvider.fit([build_index_text(chunk) for chunk in chunks])
        store = InMemoryPgVectorStore()
        store.upsert_chunks(chunks)
        store.upsert_embeddings(
            [
                PgVectorEmbeddingRecord(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    embedding_model=provider.model_name,
                    embedding_dimension=provider.dimensions,
                    embedding=embedding,
                )
                for chunk, embedding in zip(chunks, provider.embed_texts([build_index_text(chunk) for chunk in chunks]))
            ]
        )
        hybrid = HybridRetriever(
            vector_backend=PgVectorSearch(store, provider),
            keyword_backend=InMemoryKeywordSearch(chunks),
            config=HybridScoringConfig(vector_weight=0.65, keyword_weight=0.35, rrf_k=20),
        )

        results = hybrid.search(RetrievalQuery(text="pto carryover vacation policy", top_k=3))

        self.assertEqual(results[0].chunk.chunk_id, "chunk-a")
        self.assertGreater(results[0].score, results[1].score)

    def test_deterministic_reranker_promotes_skills_section_over_contact_header(self) -> None:
        header = _chunk(
            "header",
            "Nijat_CV.pdf",
            "Nijat Hasanov\nBaku, Azerbaijan\nEmail: nijat@example.com",
        )
        skills = _chunk(
            "skills",
            "Nijat_CV.pdf",
            "Technical Skills\nPython, FastAPI, PostgreSQL, Docker, Redis, SQLAlchemy",
        )

        reranked = DeterministicReranker().rerank(
            query="Review the Nijat CV and tell me his skills",
            results=[_result(header, 2.0), _result(skills, 0.4)],
        )

        self.assertEqual(reranked[0].chunk.chunk_id, "skills")

    def test_deterministic_reranker_promotes_slide_specific_chunk(self) -> None:
        paper = _chunk(
            "paper",
            "reft-paper-notes.txt",
            "REFT is a fine-tuning method discussed in the paper, but this note does not describe slide 19.",
        )
        slide = _chunk(
            "slide",
            "ReFT_Presentation_Outline.txt",
            "Slide 19: Evaluation results and limitations for ReFT.",
        )

        reranked = DeterministicReranker().rerank(
            query="What is slide 19 about in the REFT presentation?",
            results=[_result(paper, 2.0), _result(slide, 0.3)],
        )

        self.assertEqual(reranked[0].chunk.chunk_id, "slide")


if __name__ == "__main__":
    unittest.main()


def test_local_embedding_provider_is_deterministic_and_dimensioned() -> None:
    provider = HashingEmbeddingProvider(dimensions=16, model_name="local-test")

    first = provider.embed_query("PTO carryover policy")
    second = provider.embed_query("PTO carryover policy")

    assert provider.model_name == "local-test"
    assert provider.dimensions == 16
    assert first == second
    assert len(first) == 16


def test_get_embedding_provider_uses_local_fallback_by_default() -> None:
    settings = SimpleNamespace(
        embedding_provider="local",
        embedding_model="local-dev",
        embedding_dimensions=24,
    )

    provider = get_embedding_provider(settings)

    assert isinstance(provider, HashingEmbeddingProvider)
    assert provider.model_name == "local-dev"
    assert provider.dimensions == 24


def test_openai_compatible_embedding_provider_parses_response(monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def read(self):
            return b'{"data":[{"index":0,"embedding":[1,0,0]},{"index":1,"embedding":[0,2,0]}]}'

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["body"] = request.data
        return FakeResponse()

    monkeypatch.setattr("backend.app.services.embeddings.request.urlopen", fake_urlopen)
    provider = OpenAICompatibleEmbeddingProvider(
        model_name="text-embedding-3-small",
        api_key="test-key",
        base_url="https://example.test/v1/embeddings",
        dimensions=3,
        timeout_seconds=7,
    )

    embeddings = provider.embed_texts(["alpha", "beta"])

    assert captured["url"] == "https://example.test/v1/embeddings"
    assert captured["timeout"] == 7
    assert len(embeddings) == 2
    assert embeddings[0] == [1.0, 0.0, 0.0]
    assert embeddings[1] == [0.0, 1.0, 0.0]
