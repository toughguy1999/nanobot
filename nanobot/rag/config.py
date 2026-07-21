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
CHUNK_SIZE = 500
CHUNK_OVERLAP = 80
BATCH_SIZE = 8
QUERY_BATCH_SIZE = 1
MAX_LENGTH = 8192
TOP_K = 5
DEVICE = "cuda"
USE_FP16 = True
