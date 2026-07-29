"""Candidate fusion for hybrid RAG retrieval."""

from nanobot.rag.types import RetrievalCandidate


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
