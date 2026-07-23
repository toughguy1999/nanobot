"""Configuration constants for the absurd novel knowledge base."""

from pathlib import Path

from nanobot.utils.helpers import PROJECT_ROOT

RAG_ASSET_DIR: Path = PROJECT_ROOT / "rag-test"
SOURCE_DIR: Path = RAG_ASSET_DIR / "source"
MODEL_DIR: Path = RAG_ASSET_DIR / "model"
DB_DIR: Path = RAG_ASSET_DIR / "db"

COLLECTION_NAME = "novel_chapters"
MODEL_REPO = "BAAI/bge-m3"
HF_ENDPOINT = "https://hf-mirror.com"

SUPPORTED_EXTENSIONS = frozenset({".md", ".txt"})
CHUNK_MIN_SIZE = 700
CHUNK_MAX_SIZE = 1000
CHUNK_OVERLAP_SENTENCES = 2
CHUNK_OVERLAP_MAX_SIZE = 80
BATCH_SIZE = 6
QUERY_BATCH_SIZE = 1
MAX_LENGTH = 8192
TOP_K = 3
DEVICE = "cuda"
USE_FP16 = True
