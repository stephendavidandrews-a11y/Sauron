"""
sauron/scripts/backfill_embeddings.py

CLI script to backfill embeddings:
  1. Embed all beliefs (standalone)
  2. Optionally re-embed all completed conversations (to pick up beliefs)

Usage:
  python -m sauron.scripts.backfill_embeddings [--beliefs-only] [--all]
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Backfill embeddings for beliefs and conversations"
    )
    parser.add_argument(
        "--beliefs-only",
        action="store_true",
        help="Only embed beliefs, skip conversation re-embedding",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Re-embed all completed conversations (picks up belief embeddings)",
    )
    args = parser.parse_args()

    from sauron.embeddings.embedder import embed_all_beliefs, embed_conversation
    from sauron.db.connection import get_connection

    # Step 1: Embed all beliefs
    logger.info("=== Step 1: Embedding all beliefs ===")
    belief_count = embed_all_beliefs()
    logger.info("Embedded %d beliefs", belief_count)

    if args.beliefs_only:
        logger.info("Done (beliefs only).")
        return

    if not args.all:
        logger.info(
            "Skipping conversation re-embedding. Use --all to re-embed all conversations."
        )
        logger.info("Done.")
        return

    # Step 2: Re-embed all completed conversations
    logger.info("=== Step 2: Re-embedding completed conversations ===")
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id FROM conversations
            WHERE processing_status IN ('completed', 'awaiting_claim_review')
            ORDER BY captured_at DESC
            """
        ).fetchall()
    finally:
        conn.close()

    total = len(rows)
    logger.info("Found %d conversations to re-embed", total)

    embedded = 0
    for i, row in enumerate(rows):
        conv_id = row["id"]
        try:
            embed_conversation(conv_id)
            embedded += 1
        except Exception:
            logger.exception("Failed to embed conversation %s", conv_id)

        if (i + 1) % 10 == 0:
            logger.info("Progress: %d/%d conversations", i + 1, total)

        # Small delay to avoid overwhelming the system
        time.sleep(0.1)

    logger.info("Re-embedded %d/%d conversations", embedded, total)
    logger.info("Done.")


if __name__ == "__main__":
    main()
