from __future__ import annotations

from app.retrieval.interfaces import RetrievalQuery, VectorSearchBackend
from app.retrieval.storage import PgVectorStore
from app.services.document_models import SearchResult
from app.services.embeddings import EmbeddingProvider


class PgVectorSearch(VectorSearchBackend):
    def __init__(self, store: PgVectorStore, embedding_provider: EmbeddingProvider) -> None:
        self._store = store
        self._embedding_provider = embedding_provider
        self._embedding_model = getattr(embedding_provider, "model_name", "embedding-provider")
        self._embedding_dimension = getattr(embedding_provider, "dimensions", 0)

    def search(self, query: RetrievalQuery) -> list[SearchResult]:
        query_embedding = self._embedding_provider.embed_query(query.text)
        matches = self._store.vector_search(
            query_embedding,
            top_k=query.top_k,
            filters=query.filters,
            embedding_model=self._embedding_model,
            embedding_dimension=self._embedding_dimension,
        )
        results: list[SearchResult] = []
        for rank, (chunk, score) in enumerate(matches, start=1):
            results.append(
                SearchResult(
                    chunk=chunk,
                    score=score,
                    vector_score=score,
                    rank=rank,
                )
            )
        return results
