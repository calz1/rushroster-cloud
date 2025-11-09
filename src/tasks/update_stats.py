#!/usr/bin/env python3
"""
Background task to update global statistics.

This script should be run periodically (e.g., hourly) via cron:
    0 * * * * cd /path/to/rushroster-cloud && uv run python -m src.tasks.update_stats
"""

import sys
from datetime import datetime

from ..database.session import SessionLocal
from ..database import crud


def main():
    """Update global statistics."""
    print(f"[{datetime.now().isoformat()}] Starting statistics update...")

    db = SessionLocal()
    try:
        # Update statistics
        stats = crud.update_global_statistics(db)

        print(f"[{datetime.now().isoformat()}] Statistics updated successfully:")
        print(f"  - Total devices: {stats.total_devices}")
        print(f"  - Community devices: {stats.community_devices}")
        print(f"  - Total events: {stats.total_events}")
        print(f"  - Speeding events: {stats.speeding_events}")
        print(f"  - Recent events (24h): {stats.recent_events_24h}")
        print(f"  - Recent speeding (24h): {stats.recent_speeding_24h}")

        map_data = stats.statistics_data.get("map_data", []) if stats.statistics_data else []
        print(f"  - Map devices: {len(map_data)}")

        return 0

    except Exception as e:
        print(f"[{datetime.now().isoformat()}] ERROR: Failed to update statistics: {e}", file=sys.stderr)
        return 1

    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
