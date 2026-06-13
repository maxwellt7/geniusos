"""CLI entry point: run a sync from the command line.

Usage:
    python -m scripts.sync           # incremental sync
    python -m scripts.sync --full    # full re-sync from the beginning
    python -m scripts.sync --graph   # only run pending graph ingestion
"""

import argparse
import asyncio
import json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="Full re-sync")
    parser.add_argument("--graph", action="store_true", help="Only run graph ingestion")
    parser.add_argument("--graph-limit", type=int, default=None)
    args = parser.parse_args()

    from app.ingestion.pipeline import ingest_graph_pending, run_sync

    if args.graph:
        result = asyncio.run(ingest_graph_pending(limit=args.graph_limit))
    else:
        result = run_sync(full=args.full)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
