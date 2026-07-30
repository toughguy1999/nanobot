"""Candidate fusion and model reranking for hybrid RAG retrieval."""

import os
from numbers import Real
from pathlib import Path
from threading import Lock
from typing import Any

import huggingface_hub
from FlagEmbedding import FlagReranker  # type: ignore[import-untyped]

from nanobot.rag import config
from nanobot.rag.types import RetrievalCandidate

_reranker_model: Any | None = None
_reranker_model_lock = Lock()
_reranker_inference_lock = Lock()


def weighted_rrf(
    dense_candidates: list[RetrievalCandidate],
    sparse_candidates: list[RetrievalCandidate],
    dense_weight: float,
    sparse_weight: float,
    rrf_k: int,
    top_k: int,
) -> list[RetrievalCandidate]:
    """Fuse ranked dense and sparse candidates with weighted reciprocal rank."""
    scores: dict[str, float] = {}
    candidates_by_id: dict[str, RetrievalCandidate] = {}

    for candidates, weight in (
        (dense_candidates, dense_weight),
        (sparse_candidates, sparse_weight),
    ):
        for candidate in candidates:
            candidates_by_id.setdefault(candidate.chunk_id, candidate)
            scores[candidate.chunk_id] = scores.get(candidate.chunk_id, 0.0) + weight / (
                rrf_k + candidate.rank
            )

    ranked_ids = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))
    return [candidates_by_id[chunk_id] for chunk_id in ranked_ids[:top_k]]


def has_local_reranker_model(model_dir: Path) -> bool:
    """Return whether the local directory contains a complete reranker model."""
    required_files = ("config.json", "tokenizer_config.json")
    tokenizer_files = (
        "tokenizer.json",
        "sentencepiece.bpe.model",
        "spiece.model",
        "vocab.txt",
    )
    weight_files = (
        "model.safetensors",
        "model.safetensors.index.json",
        "pytorch_model.bin",
        "pytorch_model.bin.index.json",
    )
    return (
        model_dir.exists()
        and all((model_dir / file_name).is_file() for file_name in required_files)
        and any((model_dir / file_name).is_file() for file_name in tokenizer_files)
        and any((model_dir / file_name).is_file() for file_name in weight_files)
    )


def ensure_reranker_model_downloaded() -> None:
    """Ensure the configured reranker exists under its independent model directory."""
    if has_local_reranker_model(config.RERANK_MODEL_DIR):
        return

    if config.HF_ENDPOINT:
        os.environ.setdefault("HF_ENDPOINT", config.HF_ENDPOINT)

    config.RERANK_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    huggingface_hub.snapshot_download(
        repo_id=config.RERANK_MODEL_REPO,
        local_dir=str(config.RERANK_MODEL_DIR),
    )


def load_reranker_model() -> Any:
    """Return the process-lifetime reranker singleton."""
    global _reranker_model

    if _reranker_model is None:
        with _reranker_model_lock:
            if _reranker_model is None:
                ensure_reranker_model_downloaded()
                model = FlagReranker(
                    str(config.RERANK_MODEL_DIR),
                    use_fp16=config.USE_FP16,
                    devices=config.DEVICE,
                    max_length=config.MAX_LENGTH,
                )
                _reranker_model = model
    return _reranker_model


def rerank_candidates(
    query: str,
    candidates: list[RetrievalCandidate],
    top_k: int,
) -> list[RetrievalCandidate]:
    """Rank candidates by query-text relevance and return the best candidates."""
    if not candidates or top_k <= 0:
        return []

    model = load_reranker_model()
    pairs = [(query, candidate.text) for candidate in candidates]
    with _reranker_inference_lock:
        raw_scores = model.compute_score(pairs)

    scores = _normalize_scores(raw_scores)
    if len(scores) != len(candidates):
        raise ValueError(
            "reranker score count does not match candidate count: "
            f"{len(scores)} != {len(candidates)}"
        )

    ranked_indexes = sorted(range(len(candidates)), key=lambda index: -scores[index])
    return [candidates[index] for index in ranked_indexes[:top_k]]


def _normalize_scores(raw_scores: Any) -> list[float]:
    """Convert scalar or array-like model output into plain Python scores."""
    if hasattr(raw_scores, "tolist"):
        raw_scores = raw_scores.tolist()
    if isinstance(raw_scores, Real):
        return [float(raw_scores)]
    return [float(score) for score in raw_scores]
