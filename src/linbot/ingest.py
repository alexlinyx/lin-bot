"""CLI shim: `python -m linbot.ingest` re-indexes the site content."""

from linbot.retrieval.ingest import main

if __name__ == "__main__":
    main()
