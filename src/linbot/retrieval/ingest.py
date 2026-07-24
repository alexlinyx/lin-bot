"""Ingest site content from llms.txt into the chunks table.

The site publishes llms.txt (an index of markdown pages, per the llms.txt
convention) and optionally llms-full.txt (everything concatenated). We fetch
the index, follow its same-host links to markdown/text pages, chunk each page
by heading, embed the chunks, and replace each source's rows atomically.

Run with:  python -m linbot.ingest
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from urllib.parse import urljoin, urlparse

import httpx
from sqlalchemy import delete

from linbot.config import Settings, load_settings
from linbot.retrieval.embedder import VoyageEmbedder
from linbot.storage.db import create_engine, create_session_factory
from linbot.storage.models import Chunk

MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
HEADING = re.compile(r"^(#{1,3})\s+(.*)$")
MAX_CHUNK_CHARS = 2000
EMBED_BATCH_SIZE = 64


def extract_page_links(index_text: str, base_url: str) -> list[str]:
    """Same-host .md/.txt links from the llms.txt index, in order, deduped."""
    base_host = urlparse(base_url).netloc
    links: list[str] = []
    for raw in MARKDOWN_LINK.findall(index_text):
        url = urljoin(base_url, raw)
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or parsed.netloc != base_host:
            continue
        if not parsed.path.endswith((".md", ".txt")):
            continue
        if url not in links:
            links.append(url)
    return links


def _strip_frontmatter(text: str) -> str:
    """Drop a leading YAML frontmatter block (--- ... ---) — site metadata,
    not content."""
    if text.lstrip().startswith("---"):
        stripped = text.lstrip()
        end = stripped.find("\n---", 3)
        if end != -1:
            return stripped[end + 4 :].lstrip("\n")
    return text


def chunk_markdown(text: str) -> list[tuple[str | None, str]]:
    """Split by headings (#, ##, ###); oversized sections split by paragraph.

    Returns (heading, content) pairs; content includes the heading line so the
    model sees it.
    """
    text = _strip_frontmatter(text)
    sections: list[tuple[str | None, list[str]]] = [(None, [])]
    for line in text.splitlines():
        match = HEADING.match(line)
        if match:
            sections.append((match.group(2).strip(), []))
        sections[-1][1].append(line)

    chunks: list[tuple[str | None, str]] = []
    for heading, lines in sections:
        content = "\n".join(lines).strip()
        if not content:
            continue
        if len(content) <= MAX_CHUNK_CHARS:
            chunks.append((heading, content))
            continue
        part, size = [], 0
        for paragraph in content.split("\n\n"):
            if size + len(paragraph) > MAX_CHUNK_CHARS and part:
                chunks.append((heading, "\n\n".join(part)))
                part, size = [], 0
            part.append(paragraph)
            size += len(paragraph) + 2
        if part:
            chunks.append((heading, "\n\n".join(part)))
    return chunks


def _is_substantive(text: str) -> bool:
    """Filter out template stubs (e.g. an unfilled llms-full.txt)."""
    without_comments = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    return len(without_comments.strip()) > 300


async def fetch_sources(settings: Settings) -> dict[str, str]:
    """Return {source_url: text} for the index, its linked pages, and
    llms-full.txt when it has real content."""
    sources: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        index_url = settings.rag_source_url
        index = (await client.get(index_url)).raise_for_status().text
        sources[index_url] = index

        candidates = extract_page_links(index, index_url)
        full_url = urljoin(index_url, "llms-full.txt")
        if full_url not in candidates:
            candidates.append(full_url)

        for url in candidates:
            if url == index_url:
                continue
            try:
                text = (await client.get(url)).raise_for_status().text
            except httpx.HTTPError as exc:
                print(f"  skipping {url}: {exc}", file=sys.stderr)
                continue
            if _is_substantive(text):
                sources[url] = text
            else:
                print(f"  skipping {url}: template stub / too little content", file=sys.stderr)
    return sources


async def ingest(settings: Settings) -> int:
    if not settings.voyage_api_key:
        print("VOYAGE_API_KEY is required to ingest (see .env.example)", file=sys.stderr)
        raise SystemExit(1)

    embedder = VoyageEmbedder(settings.voyage_api_key, settings.voyage_model, max_retries_429=5)
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)

    sources = await fetch_sources(settings)
    total = 0
    try:
        for url, text in sources.items():
            pairs = chunk_markdown(text)
            if not pairs:
                continue
            embeddings: list[list[float]] = []
            contents = [content for _, content in pairs]
            for i in range(0, len(contents), EMBED_BATCH_SIZE):
                embeddings.extend(
                    await embedder.embed(contents[i : i + EMBED_BATCH_SIZE], "document")
                )
            # Replace this source's rows atomically so a mid-ingest crash
            # never leaves a page half-indexed.
            async with session_factory() as session:
                await session.execute(delete(Chunk).where(Chunk.source_url == url))
                for (heading, content), embedding in zip(pairs, embeddings, strict=True):
                    session.add(
                        Chunk(
                            source_url=url,
                            heading=heading,
                            content=content,
                            embedding=json.dumps(embedding),
                        )
                    )
                await session.commit()
            total += len(pairs)
            print(f"  {url}: {len(pairs)} chunks")
    finally:
        await embedder.aclose()
        await engine.dispose()
    return total


def main() -> None:
    settings = load_settings()
    print(f"Ingesting from {settings.rag_source_url} ...")
    total = asyncio.run(ingest(settings))
    print(f"Done: {total} chunks indexed.")
