"""Extraction pipeline orchestration — triage, claims, synthesis.

Functions:
  run_full_extraction_pipeline — orchestrate triage -> extract -> embed
  run_three_pass_extraction — Pass 1 (Haiku triage) + gate
  run_deep_extraction_only — Passes 2-3 (Sonnet claims + Opus synthesis)
  try_extraction_comparison — compare reprocessing results
"""
import json
import logging
import uuid
from datetime import datetime, timezone

from sauron.db.connection import get_connection
from sauron.pipeline.storage import (
    _store_episodes, _store_claims, _create_provisional_contacts,
    _store_belief_updates, _store_graph_edges, _link_meeting_intentions,
)
from sauron.pipeline.reconstruction import _load_existing_beliefs
from sauron.pipeline.helpers import _update_status, _run_embedding

logger = logging.getLogger(__name__)


def _try_extraction_comparison(conversation_id: str, new_extraction_id: str = None):
    """Compare new extraction against previous if exists (Feature 5)."""
    try:
        conn = get_connection()
        try:
            # Find the latest extraction for this conversation
            if new_extraction_id:
                prev = conn.execute(
                    """SELECT id FROM extractions
                       WHERE conversation_id = ? AND id != ?
                       ORDER BY created_at DESC LIMIT 1""",
                    (conversation_id, new_extraction_id),
                ).fetchone()
            else:
                # Get the two most recent extractions
                rows = conn.execute(
                    """SELECT id FROM extractions
                       WHERE conversation_id = ?
                       ORDER BY created_at DESC LIMIT 2""",
                    (conversation_id,),
                ).fetchall()
                if len(rows) < 2:
                    return
                new_extraction_id = rows[0]["id"]
                prev = rows[1]

            if prev:
                from sauron.learning.compare import compare_extractions
                comparison = compare_extractions(
                    conversation_id, prev["id"], new_extraction_id
                )
                if comparison:
                    logger.info(
                        "Reprocessing comparison: %d reproduced, %d missed, "
                        "%d new, %d corrections resolved",
                        comparison.get("claims_reproduced", 0),
                        comparison.get("claims_missed", 0),
                        comparison.get("claims_new", 0),
                        comparison.get("corrections_resolved", 0),
                    )
        finally:
            conn.close()
    except Exception:
        logger.exception("Extraction comparison failed (non-fatal)")


def _run_full_extraction_pipeline(
    conn, conversation_id, transcript_text, vocal_summary, speaker_map
):
    """Run the complete extraction pipeline: triage -> extract -> embed.

    Handles the triage gate: low-value -> triage_rejected, high/medium -> full extraction.
    """
    _update_status(conn, conversation_id, "triaging")
    conn.commit()

    logger.info(f"[{conversation_id[:8]}] Stage 7: Three-pass Claude extraction...")
    extraction_result = _run_three_pass_extraction(
        conn, conversation_id, transcript_text, vocal_summary,
        speaker_map=speaker_map,
    )
    conn.commit()

    # Check if triage rejected (status set inside _run_three_pass_extraction)
    status = conn.execute(
        "SELECT processing_status FROM conversations WHERE id = ?",
        (conversation_id,),
    ).fetchone()
    if status and status["processing_status"] == "triage_rejected":
        logger.info(f"[{conversation_id[:8]}] Pipeline stopped at triage_rejected")
        return True

    if extraction_result:
        logger.info(f"[{conversation_id[:8]}] Stage 8: Routing deferred until review")

    # Stage 9: Semantic embedding
    logger.info(f"[{conversation_id[:8]}] Stage 9: Semantic embedding...")
    _run_embedding(conversation_id)

    # Mark as awaiting claim review (NOT completed)
    _update_status(conn, conversation_id, "awaiting_claim_review")
    conn.commit()

    # Feature 5: Compare with previous extraction if this is a reprocessing
    _try_extraction_comparison(conversation_id)

    logger.info(f"[{conversation_id[:8]}] Pipeline complete — awaiting claim review")
    return True



def _run_three_pass_extraction(
    conn,
    conversation_id: str,
    transcript_text: str,
    vocal_summary: str | None,
    speaker_map: dict | None = None,
) -> dict | None:
    """Run three-pass Claude extraction: Haiku -> Sonnet -> Opus.

    Low-value conversations now get status triage_rejected
    instead of completing silently.
    """
    try:
        from sauron.extraction.triage import triage_conversation, should_run_deep_extraction, generate_title
        from sauron.extraction.claims import extract_claims
        from sauron.extraction.dedup import dedup_claims
        from sauron.extraction.deep import synthesize, solo_extract

        amendment_context = ""
        try:
            from sauron.learning.amendments import build_extraction_context
            amendment_context = build_extraction_context(conversation_id)
        except Exception:
            logger.debug("Amendment context unavailable (non-fatal)")

        # Pass 1: Haiku triage + episode segmentation
        triage, triage_usage = triage_conversation(
            transcript_text, amendment_context=amendment_context
        )

        conn.execute(
            """INSERT INTO extractions (id, conversation_id, pass_number, extraction_json,
               extraction_version, model_used, input_tokens, output_tokens)
               VALUES (?, ?, 1, ?, 'v6.0', ?, ?, ?)""",
            (str(uuid.uuid4()), conversation_id,
             triage.model_dump_json(), "haiku-4.5",
             triage_usage.input_tokens, triage_usage.output_tokens),
        )

        _store_episodes(conn, conversation_id, triage)

        conn.execute(
            "UPDATE conversations SET context_classification = ? WHERE id = ?",
            (triage.context_classification, conversation_id),
        )

        # Generate conversation title from triage data
        try:
            title = generate_title(triage_result=triage)
            if title:
                conn.execute(
                    "UPDATE conversations SET title = ? WHERE id = ?",
                    (title, conversation_id),
                )
                logger.info(f"[{conversation_id[:8]}] Title: {title}")
        except Exception as e:
            logger.warning(f"[{conversation_id[:8]}] Title generation failed (non-fatal): {e}")

        if not should_run_deep_extraction(triage):
            logger.info(f"Skipping deep extraction (value={triage.value_assessment})")
            # NEW: Set triage_rejected instead of letting it fall through to completed
            _update_status(conn, conversation_id, "triage_rejected")
            conn.commit()
            return triage.model_dump()

        # Update status to extracting (triage passed)
        _update_status(conn, conversation_id, "extracting")
        conn.commit()

        return _run_deep_extraction_only(
            conn, conversation_id, transcript_text, vocal_summary,
            speaker_map, triage, amendment_context
        )

    except Exception:
        logger.exception("Claude extraction failed (non-fatal)")
        return None


def _run_deep_extraction_only(
    conn,
    conversation_id: str,
    transcript_text: str,
    vocal_summary: str | None,
    speaker_map: dict | None,
    triage,
    amendment_context: str = "",
) -> dict | None:
    """Run Sonnet claims + Opus synthesis (Passes 2-3).

    Separated so it can be called independently when promoting triage-rejected conversations.
    """
    try:
        from sauron.extraction.claims import extract_claims
        from sauron.extraction.dedup import dedup_claims
        from sauron.extraction.deep import synthesize, solo_extract

        if not amendment_context:
            try:
                from sauron.learning.amendments import build_extraction_context
                amendment_context = build_extraction_context(conversation_id)
            except Exception:
                pass

        # Solo capture — simplified single-pass
        if triage.is_solo:
            result, usage = solo_extract(
                transcript_text, triage,
                amendment_context=amendment_context,
            )
            conn.execute(
                """INSERT INTO extractions (id, conversation_id, pass_number, extraction_json,
                   extraction_version, model_used, input_tokens, output_tokens)
                   VALUES (?, ?, 2, ?, 'v6.0', ?, ?, ?)""",
                (str(uuid.uuid4()), conversation_id,
                 result.model_dump_json(), "opus-4.6",
                 usage["input_tokens"], usage["output_tokens"]),
            )
            extraction_result = result.model_dump()
        else:
            # Pass 2: Sonnet claims extraction
            claims_result, claims_usage = extract_claims(
                transcript_text, triage.episodes,
                amendment_context=amendment_context,
                speaker_map=speaker_map,
                conversation_id=conversation_id,
            )

            conn.execute(
                """INSERT INTO extractions (id, conversation_id, pass_number, extraction_json,
                   extraction_version, model_used, input_tokens, output_tokens)
                   VALUES (?, ?, 2, ?, 'v6.0', ?, ?, ?)""",
                (str(uuid.uuid4()), conversation_id,
                 claims_result.model_dump_json(), "sonnet-4.6",
                 claims_usage["input_tokens"], claims_usage["output_tokens"]),
            )

            # Pass 2.5: Dedup
            pre_dedup_count = len(claims_result.claims)
            claims_result = dedup_claims(claims_result)
            post_dedup_count = len(claims_result.claims)

            # Store claims
            _store_claims(conn, conversation_id, claims_result)

            # Create provisional contacts
            _create_provisional_contacts(conn, conversation_id, claims_result)

            # Pass 2.7: Entity resolution
            try:
                from sauron.extraction.entity_resolver import resolve_claim_entities
                conn.commit()
                entity_stats = resolve_claim_entities(conversation_id)

                # Resolve non-person entities (orgs, legislation, topics)
                try:
                    from sauron.extraction.object_resolver import resolve_object_entities
                    obj_stats = resolve_object_entities(conversation_id)
                    if obj_stats.get("resolved") or obj_stats.get("created"):
                        logger.info(f"[{conversation_id[:8]}] Object resolution: {obj_stats}")
                except Exception:
                    logger.exception("Object resolution failed (non-fatal)")
                logger.info(f"[{conversation_id[:8]}] Entity resolution: {entity_stats}")
            except Exception:
                logger.exception("Entity resolution failed (non-fatal)")

            # Pass 3: Opus synthesis
            existing_beliefs = _load_existing_beliefs(conn, speaker_map)

            synthesis_result, synthesis_usage = synthesize(
                transcript_text, claims_result,
                vocal_summary=vocal_summary,
                triage=triage,
                existing_beliefs=existing_beliefs,
                amendment_context=amendment_context,
                conversation_id=conversation_id,
            )

            conn.execute(
                """INSERT INTO extractions (id, conversation_id, pass_number, extraction_json,
                   extraction_version, model_used, input_tokens, output_tokens)
                   VALUES (?, ?, 3, ?, 'v6.0', ?, ?, ?)""",
                (str(uuid.uuid4()), conversation_id,
                 synthesis_result.model_dump_json(), "opus-4.6",
                 synthesis_usage["input_tokens"], synthesis_usage["output_tokens"]),
            )

            _store_belief_updates(conn, conversation_id, synthesis_result, claims_result)
            _store_graph_edges(conn, conversation_id, synthesis_result)

            # Pass 3.5: Synthesis entity auto-linking
            try:
                from sauron.extraction.synthesis_linker import link_synthesis_entities
                conn.commit()  # Commit current work so linker gets its own connection
                linking_stats = link_synthesis_entities(conversation_id)
                logger.info(
                    f"[{conversation_id[:8]}] Synthesis entity linking: "
                    f"{linking_stats.get('resolved', 0)} resolved, "
                    f"{linking_stats.get('provisional', 0)} provisional"
                )
            except Exception:
                logger.exception("Synthesis entity linking failed (non-fatal)")

            extraction_result = {
                "triage": triage.model_dump(),
                "claims": claims_result.model_dump(),
                "synthesis": synthesis_result.model_dump(),
            }

        # Auto-link meeting intentions
        if speaker_map:
            _link_meeting_intentions(conn, conversation_id, speaker_map, extraction_result)

        return extraction_result

    except Exception:
        logger.exception("Deep extraction failed (non-fatal)")
        return None


# =====================================================
# STORAGE HELPERS
# =====================================================
