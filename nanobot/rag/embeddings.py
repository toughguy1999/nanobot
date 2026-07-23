"""Embedding model loading and text vectorization."""

import os
from pathlib import Path
from typing import Any

import huggingface_hub
from FlagEmbedding import BGEM3FlagModel  # type: ignore[import-untyped]

from nanobot.rag import config


def load_embedding_model() -> Any:
    """Load the configured local embedding model, downloading it first if needed."""
    ensure_model_downloaded()
    return BGEM3FlagModel(str(config.MODEL_DIR), use_fp16=config.USE_FP16, device=config.DEVICE)


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


def embed_texts(model: Any, texts: list[str], batch_size: int) -> list[list[float]]:
    """Encode text into plain Python dense vectors."""
    output = model.encode(texts, batch_size=batch_size, max_length=config.MAX_LENGTH)
    dense_vectors = output["dense_vecs"] if isinstance(output, dict) else output
    return [
        vector.tolist() if hasattr(vector, "tolist") else list(vector) for vector in dense_vectors
    ]
