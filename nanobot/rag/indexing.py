"""Document scanning, chunking, and chunk metadata for local RAG indexing."""

import re
from pathlib import Path

from nanobot.rag import config
from nanobot.rag.types import TextChunk

_SENTENCE_ENDINGS = re.compile(r"(?<=[。！？!?])")


def scan_source_documents(
    source_dir: Path, error_type: type[Exception] = RuntimeError
) -> list[Path]:
    """Return supported source documents in a stable order."""
    documents = sorted(
        path
        for path in source_dir.iterdir()
        if path.is_file() and path.suffix.lower() in config.SUPPORTED_EXTENSIONS
    )
    if not documents:
        raise error_type(f"No source documents found in {source_dir}")
    return documents


def build_chunks(documents: list[Path]) -> list[TextChunk]:
    """Read documents and split them into globally indexed text chunks."""
    chunks: list[TextChunk] = []
    for document in documents:
        text = document.read_text(encoding="utf-8")
        document_chunks = (
            chunk_markdown(text, document)
            if document.suffix.lower() == ".md"
            else chunk_plain_text(text, document)
        )
        chunks.extend(
            TextChunk(
                text=chunk.text,
                source_name=chunk.source_name,
                source_path=chunk.source_path,
                index=len(chunks) + index,
            )
            for index, chunk in enumerate(document_chunks)
        )
    return chunks


def chunk_markdown(markdown: str, source_path: Path) -> list[TextChunk]:
    """Split Markdown by heading, prefixing each chunk with its heading path."""
    chunks: list[TextChunk] = []
    for heading_path, paragraphs in _split_markdown_sections(markdown):
        prefix = f"标题上下文：{' > '.join(heading_path)}" if heading_path else ""
        chunks.extend(_chunk_paragraphs(paragraphs, source_path, prefix, len(chunks)))
    return chunks


def chunk_plain_text(text: str, source_path: Path) -> list[TextChunk]:
    """Split plain text at paragraph and sentence boundaries."""
    paragraphs = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    return _chunk_paragraphs(paragraphs, source_path, "", 0)


def _chunk_paragraphs(
    paragraphs: list[str], source_path: Path, prefix: str, start_index: int
) -> list[TextChunk]:
    """Pack paragraphs into chunks, falling back to sentence-aware splitting."""
    chunks: list[TextChunk] = []
    current: list[str] = []
    max_body_size = max(1, config.CHUNK_MAX_SIZE - _prefixed_length(prefix))

    def emit() -> None:
        nonlocal current
        body = "\n\n".join(current).strip()
        if not body:
            current = []
            return
        text = f"{prefix}\n\n{body}" if prefix else body
        chunks.append(
            TextChunk(
                text=text,
                source_name=source_path.name,
                source_path=source_path,
                index=start_index + len(chunks),
            )
        )
        tail = _overlap_sentences(body)
        current = [tail] if tail else []

    for paragraph in paragraphs:
        pending = [paragraph]
        while pending:
            unit = pending.pop(0)
            if not current:
                if len(unit) <= max_body_size:
                    current.append(unit)
                else:
                    pending = _split_to_limit(unit, max_body_size) + pending
                continue

            if _joined_length(current, unit) <= max_body_size:
                current.append(unit)
                continue

            emit()
            # Reconsider after adding overlap.  If needed, split this paragraph
            # at sentence boundaries to fill the remaining natural-space window.
            remaining = max_body_size - len("\n\n".join(current)) - 2
            if len(unit) > remaining:
                pending = _split_to_limit(unit, remaining) + pending
            else:
                pending.insert(0, unit)

    if current:
        emit()
    return chunks


def _split_markdown_sections(markdown: str) -> list[tuple[list[str], list[str]]]:
    """Return paragraphs grouped by their full Markdown heading path."""
    sections: list[tuple[list[str], list[str]]] = []
    heading_stack: list[tuple[int, str]] = []
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            text = "\n".join(buffer).strip()
            if text:
                if sections and sections[-1][0] == [title for _, title in heading_stack]:
                    sections[-1][1].append(text)
                else:
                    sections.append(([title for _, title in heading_stack], [text]))
            buffer.clear()

    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            flush()
            continue

        heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading:
            flush()
            level = len(heading.group(1))
            heading_stack[:] = [item for item in heading_stack if item[0] < level]
            heading_stack.append((level, heading.group(2).strip()))
            continue

        buffer.append(stripped)

    flush()
    return sections


def _prefixed_length(prefix: str) -> int:
    return len(prefix) + 2 if prefix else 0


def _joined_length(parts: list[str], addition: str) -> int:
    return len("\n\n".join([*parts, addition]))


def _split_to_limit(text: str, limit: int) -> list[str]:
    """Split long text on sentence boundaries, using hard cuts only as a fallback."""
    if limit <= 0:
        return [text]

    sentences = [sentence.strip() for sentence in _SENTENCE_ENDINGS.split(text) if sentence.strip()]
    if not sentences:
        sentences = [text]

    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        while len(sentence) > limit:
            if current:
                pieces.append(current)
                current = ""
            pieces.append(sentence[:limit].strip())
            sentence = sentence[limit:].strip()
        candidate = f"{current}{sentence}" if current else sentence
        if current and len(candidate) > limit:
            pieces.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


def _overlap_sentences(text: str) -> str:
    """Return up to two trailing whole sentences within the overlap limit."""
    sentences = [sentence.strip() for sentence in _SENTENCE_ENDINGS.split(text) if sentence.strip()]
    overlap: list[str] = []
    for sentence in reversed(sentences[-config.CHUNK_OVERLAP_SENTENCES :]):
        candidate = sentence if not overlap else f"{sentence}{''.join(overlap)}"
        if len(candidate) > config.CHUNK_OVERLAP_MAX_SIZE:
            break
        overlap.insert(0, sentence)
    return "".join(overlap)
