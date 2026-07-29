"""Embedding model loading and text vectorization."""

import os
from pathlib import Path
from threading import Lock
from typing import Any

import huggingface_hub
from FlagEmbedding import BGEM3FlagModel  # type: ignore[import-untyped]

from nanobot.rag import config
from nanobot.rag.types import SparseVector

_embedding_model: Any | None = None
_embedding_model_lock = Lock()


def load_embedding_model() -> Any:
    """Return the process-lifetime embedding model singleton."""
    global _embedding_model

    if _embedding_model is None:
        with _embedding_model_lock:
            if _embedding_model is None:
                ensure_model_downloaded()
                _embedding_model = BGEM3FlagModel(
                    str(config.MODEL_DIR), use_fp16=config.USE_FP16, device=config.DEVICE
                )
    return _embedding_model


def ensure_model_downloaded() -> None:
    """Ensure the configured Hugging Face model exists under the local model directory."""
    if has_local_model(config.MODEL_DIR):
        return

    if config.HF_ENDPOINT:
        os.environ.setdefault("HF_ENDPOINT", config.HF_ENDPOINT)

    config.MODEL_DIR.mkdir(parents=True, exist_ok=True)
    huggingface_hub.snapshot_download(repo_id=config.MODEL_REPO, local_dir=str(config.MODEL_DIR))


def has_local_model(model_dir: Path) -> bool:
    """Return whether the local directory looks like the expected embedding model."""
    required_files = [
        "config.json",
        "tokenizer_config.json",
        "sentencepiece.bpe.model",
        "pytorch_model.bin",
    ]
    return model_dir.exists() and all(
        (model_dir / file_name).is_file() for file_name in required_files
    )


def embed_texts(
    model: Any, texts: list[str], batch_size: int
) -> tuple[list[list[float]], list[SparseVector]]:
    """Encode text into plain Python dense and sparse vectors."""
    output = model.encode(
        texts,
        batch_size=batch_size,
        max_length=config.MAX_LENGTH,
        return_dense=True,
        return_sparse=True,
        return_colbert_vecs=False,
    )
    dense_vectors = [
        vector.tolist() if hasattr(vector, "tolist") else list(vector)
        for vector in output["dense_vecs"]
    ]
    sparse_vectors = [
        {
            int(token_id): float(weight)
            for token_id, weight in lexical_weights.items()
            if float(weight) > 0
        }
        for lexical_weights in output["lexical_weights"]
    ]
    return dense_vectors, sparse_vectors
