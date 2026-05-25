from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter
from hashlib import sha256
import json
from math import log, sqrt
from urllib import error, request

from app.core.config import Settings, get_settings


class EmbeddingProvider(ABC):
    model_name = "embedding-provider"
    dimensions = 0

    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def embed_query(self, query: str) -> list[float]:
        return self.embed_texts([query])[0]


class BagOfWordsEmbeddingProvider(EmbeddingProvider):
    model_name = "bag-of-words"

    def __init__(self, vocabulary: list[str] | None = None) -> None:
        self._vocabulary = vocabulary or []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not self._vocabulary:
            self._vocabulary = sorted({token for text in texts for token in _tokenize(text)})
        return [_normalize([Counter(_tokenize(text)).get(token, 0.0) for token in self._vocabulary]) for text in texts]


class TfidfEmbeddingProvider(EmbeddingProvider):
    model_name = "tfidf-v1"

    def __init__(self, vocabulary: list[str] | None = None, idf_by_term: dict[str, float] | None = None) -> None:
        self._vocabulary = vocabulary or []
        self._idf_by_term = idf_by_term or {}

    @classmethod
    def fit(cls, texts: list[str]) -> "TfidfEmbeddingProvider":
        document_tokens = [set(_tokenize(text)) for text in texts]
        vocabulary = sorted({token for tokens in document_tokens for token in tokens})
        total_documents = max(len(texts), 1)
        document_frequencies = Counter(token for tokens in document_tokens for token in tokens)
        idf_by_term = {
            token: log(1 + ((total_documents + 1) / (document_frequencies[token] + 1))) + 1.0
            for token in vocabulary
        }
        return cls(vocabulary=vocabulary, idf_by_term=idf_by_term)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not self._vocabulary:
            fitted = TfidfEmbeddingProvider.fit(texts)
            self._vocabulary = fitted._vocabulary
            self._idf_by_term = fitted._idf_by_term

        embeddings: list[list[float]] = []
        for text in texts:
            token_counts = Counter(_tokenize(text))
            max_frequency = max(token_counts.values(), default=0)
            vector: list[float] = []
            for token in self._vocabulary:
                frequency = token_counts.get(token, 0)
                if not frequency or not max_frequency:
                    vector.append(0.0)
                    continue
                term_frequency = 0.5 + (0.5 * frequency / max_frequency)
                vector.append(term_frequency * self._idf_by_term.get(token, 1.0))
            embeddings.append(_normalize(vector))
        return embeddings


class HashingEmbeddingProvider(EmbeddingProvider):
    model_name = "local-hashing-v1"

    def __init__(self, dimensions: int = 256, model_name: str | None = None) -> None:
        self._dimensions = dimensions
        self.dimensions = dimensions
        self.model_name = model_name or self.model_name

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_text(text) for text in texts]

    def _embed_text(self, text: str) -> list[float]:
        vector = [0.0] * self._dimensions
        token_counts = Counter(_tokenize(text))
        if not token_counts:
            return vector

        max_frequency = max(token_counts.values())
        for token, frequency in token_counts.items():
            bucket_hash = sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(bucket_hash[:4], "big") % self._dimensions
            sign = 1.0 if bucket_hash[4] % 2 == 0 else -1.0
            tf_weight = 0.5 + (0.5 * frequency / max_frequency)
            idf_hint = 1.0 + log(1 + len(token))
            vector[bucket] += sign * tf_weight * idf_hint
        return _normalize(vector)


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        *,
        model_name: str,
        api_key: str,
        base_url: str,
        dimensions: int,
        timeout_seconds: int = 30,
    ) -> None:
        self.model_name = model_name
        self.dimensions = dimensions
        self._api_key = api_key
        self._base_url = base_url
        self._timeout_seconds = timeout_seconds

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        body: dict[str, object] = {
            "model": self.model_name,
            "input": texts,
        }
        if self.dimensions:
            body["dimensions"] = self.dimensions

        http_request = request.Request(
            self._base_url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=self._timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            message = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"embedding request failed: {exc.code} {message}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"embedding request failed: {exc.reason}") from exc

        rows = payload.get("data")
        if not isinstance(rows, list):
            raise RuntimeError("embedding response did not contain data")

        ordered_rows = sorted(rows, key=lambda row: row.get("index", 0) if isinstance(row, dict) else 0)
        embeddings: list[list[float]] = []
        for row in ordered_rows:
            if not isinstance(row, dict) or not isinstance(row.get("embedding"), list):
                raise RuntimeError("embedding response row did not contain an embedding")
            embedding = [float(value) for value in row["embedding"]]
            if self.dimensions and len(embedding) != self.dimensions:
                raise RuntimeError(
                    f"embedding response dimension mismatch: expected {self.dimensions}, got {len(embedding)}"
                )
            embeddings.append(_normalize(embedding))
        if len(embeddings) != len(texts):
            raise RuntimeError(f"embedding response count mismatch: expected {len(texts)}, got {len(embeddings)}")
        return embeddings


def get_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    resolved_settings = settings or get_settings()
    if resolved_settings.embedding_provider == "openai_compatible":
        if not resolved_settings.embedding_api_key:
            raise RuntimeError("APP_EMBEDDING_API_KEY is required when APP_EMBEDDING_PROVIDER=openai_compatible")
        return OpenAICompatibleEmbeddingProvider(
            model_name=resolved_settings.embedding_model,
            api_key=resolved_settings.embedding_api_key,
            base_url=resolved_settings.embedding_base_url,
            dimensions=resolved_settings.embedding_dimensions,
            timeout_seconds=resolved_settings.embedding_timeout_seconds,
        )
    return HashingEmbeddingProvider(
        dimensions=resolved_settings.embedding_dimensions,
        model_name=resolved_settings.embedding_model,
    )


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    numerator = sum(left_value * right_value for left_value, right_value in zip(left, right))
    left_norm = sqrt(sum(value * value for value in left))
    right_norm = sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


def _normalize(vector: list[float]) -> list[float]:
    norm = sqrt(sum(value * value for value in vector))
    if not norm:
        return vector
    return [value / norm for value in vector]


def _tokenize(text: str) -> list[str]:
    normalized = "".join(char.lower() if char.isalnum() else " " for char in text)
    tokens = [token for token in normalized.split() if token]
    base_tokens = [_normalize_token(token) for token in tokens]
    base_tokens = [token for token in base_tokens if token and token not in _STOPWORDS]

    expanded_tokens = list(base_tokens)
    expanded_tokens.extend(
        f"{base_tokens[index]}_{base_tokens[index + 1]}"
        for index in range(len(base_tokens) - 1)
    )
    return expanded_tokens


def _normalize_token(token: str) -> str:
    if token.endswith("ies") and len(token) > 4:
        return f"{token[:-3]}y"
    if token.endswith("ing") and len(token) > 5:
        return token[:-3]
    if token.endswith("ed") and len(token) > 4:
        return token[:-2]
    if token.endswith("s") and len(token) > 3 and not token.endswith("ss"):
        return token[:-1]
    return token


_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
}
