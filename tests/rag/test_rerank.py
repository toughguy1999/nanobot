from nanobot.rag.rerank import weighted_rrf
from nanobot.rag.types import RetrievalCandidate


def _candidate(chunk_id: str, rank: int) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=chunk_id,
        text=f"text-{chunk_id}",
        metadata={"source": chunk_id},
        rank=rank,
    )


def test_weighted_rrf_deduplicates_and_accumulates_branch_scores() -> None:
    result = weighted_rrf(
        dense_candidates=[_candidate("shared", 2), _candidate("dense", 1)],
        sparse_candidates=[_candidate("shared", 1), _candidate("sparse", 2)],
        dense_weight=1.0,
        sparse_weight=2.0,
        rrf_k=10,
        top_k=2,
    )

    assert [candidate.chunk_id for candidate in result] == ["shared", "sparse"]
    assert result[0].text == "text-shared"


def test_weighted_rrf_uses_stable_id_for_equal_scores_and_applies_top_k() -> None:
    result = weighted_rrf(
        dense_candidates=[_candidate("b", 1)],
        sparse_candidates=[_candidate("a", 1)],
        dense_weight=1.0,
        sparse_weight=1.0,
        rrf_k=60,
        top_k=1,
    )

    assert [candidate.chunk_id for candidate in result] == ["a"]
