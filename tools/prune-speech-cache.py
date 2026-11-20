#!/usr/bin/env python3
"""Remove expired or least recently used Auto-Dubbing speech clips."""
import argparse
import json
from pathlib import Path

from speech_cache import prune_cached_clips


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cache", type=Path)
    parser.add_argument("--max-age-days", type=int)
    parser.add_argument("--max-bytes", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    limits = [limit for limit in (args.max_age_days, args.max_bytes) if limit is not None]
    if not limits or any(limit < 0 for limit in limits):
        parser.error("Set at least one non-negative retention limit")
    try:
        print(json.dumps(prune_cached_clips(
            args.cache, max_age_days=args.max_age_days, max_bytes=args.max_bytes,
            dry_run=args.dry_run,
        )))
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
