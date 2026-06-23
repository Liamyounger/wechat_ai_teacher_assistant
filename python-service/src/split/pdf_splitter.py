import logging
import os
import shutil
from pathlib import Path
from PyPDF2 import PdfReader, PdfWriter

logger = logging.getLogger(__name__)

# iLink file size limit in bytes
MAX_CHUNK_BYTES = 19 * 1024 * 1024  # 19MB — leave 1MB margin below 20MB limit


def split_pdf_if_needed(file_path: str, max_bytes: int = MAX_CHUNK_BYTES) -> list[str]:
    """Split a PDF into chunks under max_bytes. Returns list of output file paths.

    If the file is under the limit, returns [file_path] unchanged.
    The output chunks are placed alongside the original file with _part1, _part2 suffixes.
    """
    path = Path(file_path)
    file_size = path.stat().st_size

    if file_size <= max_bytes:
        return [file_path]

    logger.info(f"PDF {path.name} is {file_size / 1024 / 1024:.1f}MB — splitting into chunks")

    reader = PdfReader(str(path))
    total_pages = len(reader.pages)

    if total_pages == 0:
        return [file_path]

    # Estimate bytes per page from the first few pages
    sample_pages = min(10, total_pages)
    sample_size = _estimate_sample_size(path, sample_pages, total_pages)
    bytes_per_page = sample_size / sample_pages if sample_pages > 0 else file_size / total_pages

    # Calculate pages per chunk (reserving 5% margin for variance)
    pages_per_chunk = max(1, int(max_bytes / (bytes_per_page * 1.05)))

    chunk_paths = []
    stem = path.stem
    parent = path.parent
    part = 1

    for start_page in range(0, total_pages, pages_per_chunk):
        end_page = min(start_page + pages_per_chunk, total_pages)
        writer = PdfWriter()

        for i in range(start_page, end_page):
            writer.add_page(reader.pages[i])

        chunk_name = f"{stem}_part{part}.pdf"
        chunk_path = parent / chunk_name
        with open(chunk_path, "wb") as f:
            writer.write(f)

        chunk_size = chunk_path.stat().st_size
        logger.info(f"  Chunk {part}: pages {start_page + 1}-{end_page}, "
                    f"{chunk_size / 1024 / 1024:.1f}MB")

        # If the chunk is still too large (variance), split finer
        if chunk_size > max_bytes and pages_per_chunk > 1:
            # Re-split this chunk with half the pages
            sub_paths = _resplit_chunk(chunk_path, max_bytes)
            chunk_paths.extend(sub_paths)
        else:
            chunk_paths.append(str(chunk_path))

        part += 1

    return chunk_paths


def _estimate_sample_size(path: Path, sample_pages: int, total_pages: int) -> int:
    """Estimate the size of sample_pages by writing them to a temp file."""
    reader = PdfReader(str(path))
    writer = PdfWriter()
    actual = min(sample_pages, total_pages)
    for i in range(actual):
        writer.add_page(reader.pages[i])

    tmp = path.parent / f"_sample_{path.name}"
    with open(tmp, "wb") as f:
        writer.write(f)
    size = tmp.stat().st_size
    tmp.unlink(missing_ok=True)
    return size


def _resplit_chunk(chunk_path: Path, max_bytes: int) -> list[str]:
    """Re-split a chunk that's still too large — split by half pages."""
    reader = PdfReader(str(chunk_path))
    total_pages = len(reader.pages)
    if total_pages <= 1:
        return [str(chunk_path)]

    mid = total_pages // 2
    stem = chunk_path.stem
    parent = chunk_path.parent
    results = []

    for i, (start, end) in enumerate([(0, mid), (mid, total_pages)]):
        writer = PdfWriter()
        for p in range(start, end):
            writer.add_page(reader.pages[p])
        sub_path = parent / f"{stem}_sub{i + 1}.pdf"
        with open(sub_path, "wb") as f:
            writer.write(f)
        if sub_path.stat().st_size > max_bytes:
            results.extend(_resplit_chunk(sub_path, max_bytes))
        else:
            results.append(str(sub_path))

    # Remove the oversized original chunk
    chunk_path.unlink(missing_ok=True)
    return results


def cleanup_chunks(chunk_paths: list[str], original_path: str) -> None:
    """Remove chunk files that are not the original file."""
    for p in chunk_paths:
        if p != original_path:
            Path(p).unlink(missing_ok=True)
