"""CLI tool to inspect and clean up ChromaDB chunks.

Usage:
    python -m rag.manage_chunks stats
    python -m rag.manage_chunks breakdown
    python -m rag.manage_chunks list --type meta_snapshot
    python -m rag.manage_chunks list --date 2026-03-15
    python -m rag.manage_chunks list --type video_guide --show-text
    python -m rag.manage_chunks delete --type test_snapshot
    python -m rag.manage_chunks delete --date 2026-03-01
    python -m rag.manage_chunks delete --before 2026-03-10
"""

import argparse
import sys
from collections import Counter
from datetime import datetime

from rag.vector_store import TFTVectorStore


def cmd_stats(store: TFTVectorStore, _args):
    """Show total chunk count."""
    print(f"Total chunks: {store.collection.count()}")


def cmd_breakdown(store: TFTVectorStore, _args):
    """Show chunk counts grouped by type and date."""
    all_meta = store.get_all_metadata()
    if not all_meta:
        print("No chunks in the collection.")
        return

    type_counts = Counter()
    date_counts = Counter()
    type_date_counts = Counter()

    for m in all_meta:
        t = m.get("type", "unknown")
        d = m.get("date", "unknown")
        type_counts[t] += 1
        date_counts[d] += 1
        type_date_counts[(t, d)] += 1

    print(f"\nTotal chunks: {len(all_meta)}\n")

    print("By type:")
    for t, c in type_counts.most_common():
        print(f"  {t:30s} {c:5d}")

    print("\nBy date:")
    for d, c in sorted(date_counts.items()):
        print(f"  {d:30s} {c:5d}")

    print("\nBy type + date:")
    for (t, d), c in sorted(type_date_counts.items()):
        print(f"  {t:20s}  {d:12s}  {c:5d}")


def cmd_list(store: TFTVectorStore, args):
    """List chunks matching a filter."""
    where = _build_where(args)
    if not where:
        print("Provide at least one filter: --type or --date")
        return

    result = store.get_chunks_by_filter(where, include_documents=args.show_text)
    ids = result["ids"]
    metadatas = result["metadatas"]

    print(f"Found {len(ids)} chunks:\n")
    for i, (cid, meta) in enumerate(zip(ids, metadatas)):
        print(f"  [{i+1}] id={cid[:12]}...  type={meta.get('type')}  date={meta.get('date')}  chunk_index={meta.get('chunk_index')}")
        if args.show_text and result.get("documents"):
            text = result["documents"][i]
            preview = text[:200].replace("\n", " ")
            print(f"       {preview}...")
        if i >= 99:
            print(f"  ... and {len(ids) - 100} more")
            break


def cmd_delete(store: TFTVectorStore, args):
    """Delete chunks matching a filter."""
    if args.before:
        _delete_before(store, args.before)
        return

    where = _build_where(args)
    if not where:
        print("Provide at least one filter: --type, --date, or --before")
        return

    # Preview what will be deleted
    result = store.get_chunks_by_filter(where)
    count = len(result["ids"])
    if count == 0:
        print("No chunks match that filter.")
        return

    print(f"This will delete {count} chunks.")
    confirm = input("Proceed? [y/N] ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    deleted = store.delete_by_filter(where)
    print(f"Deleted {deleted} chunks. Remaining: {store.collection.count()}")


def _delete_before(store: TFTVectorStore, before_date: str):
    """Delete all chunks with date before the given date string."""
    all_meta = store.get_all_metadata()
    result = store.collection.get(include=["metadatas"])
    ids_to_delete = []

    for cid, meta in zip(result["ids"], result["metadatas"]):
        d = meta.get("date", "")
        if d and d < before_date:
            ids_to_delete.append(cid)

    if not ids_to_delete:
        print(f"No chunks found with date before {before_date}.")
        return

    print(f"This will delete {len(ids_to_delete)} chunks with date before {before_date}.")
    confirm = input("Proceed? [y/N] ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    deleted = store.delete_by_ids(ids_to_delete)
    print(f"Deleted {deleted} chunks. Remaining: {store.collection.count()}")


def _build_where(args) -> dict | None:
    """Build a ChromaDB where filter from CLI args."""
    conditions = []
    if getattr(args, "type", None):
        conditions.append({"type": args.type})
    if getattr(args, "date", None):
        conditions.append({"date": args.date})

    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Manage ChromaDB chunks")
    parser.add_argument("--db", default="./chroma_db", help="ChromaDB directory")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("stats", help="Show total chunk count")
    sub.add_parser("breakdown", help="Show chunks grouped by type and date")

    p_list = sub.add_parser("list", help="List chunks matching a filter")
    p_list.add_argument("--type", help="Filter by document type")
    p_list.add_argument("--date", help="Filter by date (YYYY-MM-DD)")
    p_list.add_argument("--show-text", action="store_true", help="Show text preview")

    p_del = sub.add_parser("delete", help="Delete chunks matching a filter")
    p_del.add_argument("--type", help="Filter by document type")
    p_del.add_argument("--date", help="Filter by exact date (YYYY-MM-DD)")
    p_del.add_argument("--before", help="Delete all chunks before this date (YYYY-MM-DD)")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    store = TFTVectorStore(persist_dir=args.db)

    commands = {
        "stats": cmd_stats,
        "breakdown": cmd_breakdown,
        "list": cmd_list,
        "delete": cmd_delete,
    }
    commands[args.command](store, args)


if __name__ == "__main__":
    main()
