"""CLI entry point for Part 1 of the travel-conditions agent.

Examples:
    python main.py --query "Quiet hill station near Delhi, 4 days early October, mid-range, photography, by road within 8h"
    python main.py --query-file my_query.txt --model Qwen/Qwen2.5-72B-Instruct
    python main.py --query "..." --no-save        # skip Google Drive upload
"""

import argparse
import asyncio
import json
import sys

from src.pipeline import run_part1
from src.settings import DEFAULT_MODEL, DRIVE_FOLDER_ID


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Travel conditions -> research + ranked destinations (Part 1)")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--query", help="Free-form travel conditions")
    src.add_argument("--query-file", help="Path to a file containing the travel conditions")
    p.add_argument("--model", default=DEFAULT_MODEL, help=f"Model (default: {DEFAULT_MODEL})")
    p.add_argument("--folder-id", default=DRIVE_FOLDER_ID, help="Google Drive folder ID for output")
    p.add_argument("--no-save", action="store_true", help="Do not upload templates to Google Drive")
    p.add_argument("--json", action="store_true", help="Print the full result as JSON")
    return p.parse_args(argv)


async def _main_async(args):
    query = args.query if args.query else open(args.query_file).read()
    result = await run_part1(
        query,
        model=args.model,
        drive_folder_id=args.folder_id,
        save=not args.no_save,
        on_event=lambda msg: print(msg, file=sys.stderr),
    )

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    print("\n=== PARSED CONDITIONS ===")
    print(json.dumps(result["stage1"]["parsed_conditions"], indent=2, ensure_ascii=False))
    if result["stage1"].get("assumptions"):
        print("\nAssumptions:")
        for a in result["stage1"]["assumptions"]:
            print(f"  - {a}")
    print("\n=== RANKED DESTINATIONS + ITINERARY TEMPLATE ===\n")
    print(result["ranked_markdown"])


def main():
    args = parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
