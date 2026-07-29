from typing import Any

from nanobot.rag import config
from nanobot.rag.embeddings import embed_texts


def test_embed_texts_requests_dense_and_sparse_vectors() -> None:
    calls: list[dict[str, Any]] = []

    class FakeArray:
        def tolist(self) -> list[float]:
            return [1.0, 2.0]

    class FakeModel:
        def encode(self, texts: list[str], **kwargs: Any) -> dict[str, Any]:
            calls.append({"texts": texts, **kwargs})
            return {
                "dense_vecs": [FakeArray()],
                "lexical_weights": [{"123": 0.5, "456": 0, "789": -0.25}],
            }

    dense, sparse = embed_texts(FakeModel(), ["query"], batch_size=2)

    assert dense == [[1.0, 2.0]]
    assert sparse == [{123: 0.5}]
    assert calls == [
        {
            "texts": ["query"],
            "batch_size": 2,
            "max_length": config.MAX_LENGTH,
            "return_dense": True,
            "return_sparse": True,
            "return_colbert_vecs": False,
        }
    ]
    assert all(type(token_id) is int for token_id in sparse[0])
    assert all(type(weight) is float for weight in sparse[0].values())
