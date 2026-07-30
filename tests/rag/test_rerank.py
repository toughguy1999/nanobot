import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from nanobot.rag import config, rerank
from nanobot.rag.types import RetrievalCandidate


@pytest.fixture(autouse=True)
def reset_reranker_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rerank, "_reranker_model", None)


def _candidate(chunk_id: str, rank: int) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=chunk_id,
        text=f"text-{chunk_id}",
        metadata={"source": chunk_id},
        rank=rank,
    )


def test_weighted_rrf_deduplicates_and_accumulates_branch_scores() -> None:
    result = rerank.weighted_rrf(
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
    result = rerank.weighted_rrf(
        dense_candidates=[_candidate("b", 1)],
        sparse_candidates=[_candidate("a", 1)],
        dense_weight=1.0,
        sparse_weight=1.0,
        rrf_k=60,
        top_k=1,
    )

    assert [candidate.chunk_id for candidate in result] == ["a"]


def test_rerank_candidates_sorts_scores_and_preserves_tie_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates = [_candidate(str(index), index + 1) for index in range(4)]

    class FakeModel:
        def compute_score(self, pairs: list[tuple[str, str]]) -> list[float]:
            assert pairs == [
                ("query", "text-0"),
                ("query", "text-1"),
                ("query", "text-2"),
                ("query", "text-3"),
            ]
            return [0.1, 0.9, 0.9, 0.2]

    monkeypatch.setattr(rerank, "load_reranker_model", lambda: FakeModel())

    result = rerank.rerank_candidates("query", candidates, top_k=3)

    assert [candidate.chunk_id for candidate in result] == ["1", "2", "3"]


def test_rerank_candidates_normalizes_scalar_and_array_outputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeArray:
        def tolist(self) -> list[float]:
            return [0.1, 0.8]

    outputs: list[Any] = [0.5, FakeArray()]
    monkeypatch.setattr(
        rerank,
        "load_reranker_model",
        lambda: type(
            "FakeModel",
            (),
            {"compute_score": lambda _self, _pairs: outputs.pop(0)},
        )(),
    )

    assert rerank.rerank_candidates("q", [_candidate("one", 1)], 3) == [
        _candidate("one", 1)
    ]
    assert [
        candidate.chunk_id
        for candidate in rerank.rerank_candidates(
            "q", [_candidate("low", 1), _candidate("high", 2)], 3
        )
    ] == ["high", "low"]


def test_rerank_candidates_rejects_mismatched_score_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = type(
        "FakeModel",
        (),
        {"compute_score": lambda _self, _pairs: [0.5]},
    )()
    monkeypatch.setattr(rerank, "load_reranker_model", lambda: model)

    with pytest.raises(ValueError, match="score count"):
        rerank.rerank_candidates(
            "q", [_candidate("one", 1), _candidate("two", 2)], 3
        )


def test_empty_candidates_do_not_load_reranker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        rerank,
        "load_reranker_model",
        lambda: pytest.fail("model must not load"),
    )

    assert rerank.rerank_candidates("q", [], 3) == []
    assert rerank.rerank_candidates("q", [_candidate("one", 1)], 0) == []


def test_local_reranker_model_skips_download(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for file_name in (
        "config.json",
        "tokenizer_config.json",
        "tokenizer.json",
        "model.safetensors",
    ):
        (tmp_path / file_name).write_text("present", encoding="utf-8")

    monkeypatch.setattr(config, "RERANK_MODEL_DIR", tmp_path)
    monkeypatch.setattr(
        rerank.huggingface_hub,
        "snapshot_download",
        lambda **_kwargs: pytest.fail("download must not run"),
    )

    rerank.ensure_reranker_model_downloaded()


def test_missing_reranker_model_downloads_to_independent_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    model_dir = tmp_path / "reranker"
    calls: list[dict[str, str]] = []
    monkeypatch.setattr(config, "RERANK_MODEL_DIR", model_dir)
    monkeypatch.setattr(config, "RERANK_MODEL_REPO", "test/reranker")
    monkeypatch.setattr(
        rerank.huggingface_hub,
        "snapshot_download",
        lambda **kwargs: calls.append(kwargs),
    )

    rerank.ensure_reranker_model_downloaded()

    assert model_dir.is_dir()
    assert calls == [{"repo_id": "test/reranker", "local_dir": str(model_dir)}]


def test_load_reranker_reuses_instance_and_configuration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    model = object()

    def fake_constructor(path: str, **kwargs: Any) -> object:
        calls.append((path, kwargs))
        return model

    monkeypatch.setattr(config, "RERANK_MODEL_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICE", "test-device")
    monkeypatch.setattr(config, "USE_FP16", False)
    monkeypatch.setattr(config, "MAX_LENGTH", 123)
    monkeypatch.setattr(rerank, "ensure_reranker_model_downloaded", lambda: None)
    monkeypatch.setattr(rerank, "FlagReranker", fake_constructor)

    assert rerank.load_reranker_model() is model
    assert rerank.load_reranker_model() is model
    assert calls == [
        (
            str(tmp_path),
            {
                "use_fp16": False,
                "devices": "test-device",
                "max_length": 123,
            },
        )
    ]


def test_failed_load_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0
    model = object()

    def fake_constructor(*_args: object, **_kwargs: object) -> object:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("load failed")
        return model

    monkeypatch.setattr(rerank, "ensure_reranker_model_downloaded", lambda: None)
    monkeypatch.setattr(rerank, "FlagReranker", fake_constructor)

    with pytest.raises(RuntimeError, match="load failed"):
        rerank.load_reranker_model()

    assert rerank._reranker_model is None
    assert rerank.load_reranker_model() is model
    assert attempts == 2


def test_failed_inference_keeps_loaded_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeModel:
        def compute_score(self, _pairs: list[tuple[str, str]]) -> list[float]:
            raise RuntimeError("inference failed")

    model = FakeModel()
    monkeypatch.setattr(rerank, "_reranker_model", model)

    with pytest.raises(RuntimeError, match="inference failed"):
        rerank.rerank_candidates("q", [_candidate("one", 1)], 1)

    assert rerank._reranker_model is model


def test_concurrent_first_load_creates_one_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructor_calls = 0
    model = object()
    start = threading.Barrier(5)

    def fake_constructor(*_args: object, **_kwargs: object) -> object:
        nonlocal constructor_calls
        constructor_calls += 1
        time.sleep(0.02)
        return model

    def load_after_barrier() -> object:
        start.wait()
        return rerank.load_reranker_model()

    monkeypatch.setattr(rerank, "ensure_reranker_model_downloaded", lambda: None)
    monkeypatch.setattr(rerank, "FlagReranker", fake_constructor)

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(load_after_barrier) for _ in range(4)]
        start.wait()
        results = [future.result() for future in futures]

    assert results == [model] * 4
    assert constructor_calls == 1


def test_concurrent_inference_is_serialized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_lock = threading.Lock()
    active_calls = 0
    max_active_calls = 0
    start = threading.Barrier(5)

    class FakeModel:
        def compute_score(self, _pairs: list[tuple[str, str]]) -> list[float]:
            nonlocal active_calls, max_active_calls
            with state_lock:
                active_calls += 1
                max_active_calls = max(max_active_calls, active_calls)
            time.sleep(0.02)
            with state_lock:
                active_calls -= 1
            return [1.0]

    def rerank_after_barrier() -> list[RetrievalCandidate]:
        start.wait()
        return rerank.rerank_candidates("q", [_candidate("one", 1)], 1)

    monkeypatch.setattr(rerank, "load_reranker_model", lambda: FakeModel())

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(rerank_after_barrier) for _ in range(4)]
        start.wait()
        for future in futures:
            assert future.result()[0].chunk_id == "one"

    assert max_active_calls == 1
