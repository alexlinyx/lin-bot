import json

import pytest
import respx
from httpx import Response

from linbot.retrieval.embedder import FakeEmbedder, RetrievalError, VoyageEmbedder
from linbot.retrieval.ingest import _is_substantive, chunk_markdown, extract_page_links
from linbot.retrieval.retriever import Retriever
from linbot.storage.models import Chunk


def test_extract_page_links_same_host_md_txt_only():
    index = """# Me
[About](https://alexlinyx.com/content/about.md)
[Rel](/content/classes.md)
[Full](llms-full.txt)
[GitHub](https://github.com/alexlinyx)
[Mail](mailto:me@example.com)
[HTML page](https://alexlinyx.com/about.html)
[About again](https://alexlinyx.com/content/about.md)
"""
    links = extract_page_links(index, "https://alexlinyx.com/llms.txt")
    assert links == [
        "https://alexlinyx.com/content/about.md",
        "https://alexlinyx.com/content/classes.md",
        "https://alexlinyx.com/llms-full.txt",
    ]


@respx.mock
async def test_fetch_sources_excludes_llms_full(tmp_path):
    from linbot.retrieval.ingest import fetch_sources
    from tests.conftest import make_settings

    index = "[About](/content/about.md)\n[Full](/llms-full.txt)\n"
    respx.get("https://alexlinyx.com/llms.txt").mock(return_value=Response(200, text=index))
    respx.get("https://alexlinyx.com/content/about.md").mock(
        return_value=Response(200, text="# About\n" + "real content " * 50)
    )
    full = respx.get("https://alexlinyx.com/llms-full.txt").mock(
        return_value=Response(200, text="# Full\n" + "real content " * 50)
    )

    sources = await fetch_sources(
        make_settings(tmp_path, rag_source_url="https://alexlinyx.com/llms.txt")
    )
    assert set(sources) == {
        "https://alexlinyx.com/llms.txt",
        "https://alexlinyx.com/content/about.md",
    }
    assert not full.called


def test_chunk_markdown_splits_by_heading():
    text = "intro line\n\n# One\nalpha\n\n## Two\nbeta\ngamma\n"
    chunks = chunk_markdown(text)
    assert [h for h, _ in chunks] == [None, "One", "Two"]
    assert "alpha" in chunks[1][1]
    assert chunks[1][1].startswith("# One")


def test_chunk_markdown_splits_oversized_sections():
    paragraphs = "\n\n".join(f"paragraph {i} " + "x" * 400 for i in range(10))
    chunks = chunk_markdown(f"# Big\n{paragraphs}")
    assert len(chunks) > 1
    assert all(h == "Big" for h, _ in chunks)
    assert all(len(c) <= 2500 for _, c in chunks)


def test_chunk_markdown_strips_frontmatter():
    text = "---\nbrand: bws\ntitle: x\n---\n\n# Real\ncontent here\n"
    chunks = chunk_markdown(text)
    assert [h for h, _ in chunks] == ["Real"]


def test_stub_detection():
    assert not _is_substantive("# Title\n<!-- TODO: paste content/about.md here -->\n")
    assert _is_substantive("# Title\n" + "real content " * 50)


async def seed_chunks(app, embedder, docs):
    embeddings = await embedder.embed([c for _, c in docs], "document")
    async with app.state.session_factory() as session:
        for (heading, content), emb in zip(docs, embeddings, strict=True):
            session.add(
                Chunk(
                    source_url="https://alexlinyx.com/content/about.md",
                    heading=heading,
                    content=content,
                    embedding=json.dumps(emb),
                )
            )
        await session.commit()


async def test_retriever_ranks_by_similarity(app):
    embedder = FakeEmbedder()
    await seed_chunks(
        app,
        embedder,
        [
            ("Teaching", "Alex teaches computer science courses at Brentwood School"),
            ("Cooking", "favorite pasta recipes with tomato basil garlic"),
        ],
    )
    retriever = Retriever(embedder, app.state.session_factory, top_k=1, min_similarity=0.0)
    results = await retriever.retrieve("who teaches computer science courses")
    assert len(results) == 1
    assert results[0].heading == "Teaching"
    assert "source:" in results[0].as_context()


async def test_retriever_min_similarity_filters(app):
    embedder = FakeEmbedder()
    await seed_chunks(app, embedder, [("Cooking", "pasta tomato basil")])
    retriever = Retriever(embedder, app.state.session_factory, top_k=4, min_similarity=0.99)
    assert await retriever.retrieve("completely unrelated astrophysics question") == []


async def test_retriever_degrades_on_embedding_failure(app):
    class BrokenEmbedder:
        async def embed(self, texts, input_type):
            raise RetrievalError("down")

    retriever = Retriever(BrokenEmbedder(), app.state.session_factory)
    assert await retriever.retrieve("anything") == []


@respx.mock
async def test_voyage_embedder_wire_shape():
    route = respx.post("https://api.voyageai.com/v1/embeddings").mock(
        return_value=Response(
            200, json={"data": [{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}]}
        )
    )
    embedder = VoyageEmbedder("pa-test", "voyage-3.5-lite")
    vectors = await embedder.embed(["a", "b"], input_type="document")
    await embedder.aclose()

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    body = json.loads(route.calls.last.request.content)
    assert body == {"input": ["a", "b"], "model": "voyage-3.5-lite", "input_type": "document"}
    assert route.calls.last.request.headers["authorization"] == "Bearer pa-test"


@respx.mock
async def test_voyage_error_becomes_retrieval_error():
    respx.post("https://api.voyageai.com/v1/embeddings").mock(return_value=Response(429))
    embedder = VoyageEmbedder("pa-test", "voyage-3.5-lite")
    with pytest.raises(RetrievalError, match="429"):
        await embedder.embed(["a"], input_type="query")
    await embedder.aclose()
