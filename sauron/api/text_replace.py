"""Conversation-scoped text replacement API.

After linking/creating a contact during People review, the user can
find-and-replace misheard names in all text objects within that conversation.

Two-phase workflow:
  1. Preview: scan conversation-scoped records for find_text matches
  2. Apply: execute user-approved changes, re-embed, log correction

Endpoints mounted under /text-replace prefix via main.py router registration.
"""

import uuid
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from sauron.db.connection import get_connection
from sauron.extraction.register_aware_replace import (
    register_aware_replace,
    Confidence,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/text-replace", tags=["text-replace"])


# ── Request / Response Models ──────────────────────────────────

class PreviewRequest(BaseModel):
    conversation_id: str
    find_text: str
    replace_with: str


class ApplyRequest(BaseModel):
    conversation_id: str
    find_text: str
    replace_with: str
    change_ids: list[str]
    edited_changes: list[dict] = []  # [{id: str, custom_text: str}]


class ChangeItem(BaseModel):
    change_id: str
    table: str
    row_id: str
    field: str
    before: str
    after: str
    confidence: str
    register: str
    skipped: bool = False
    skip_reason: Optional[str] = None


# ── Helpers ────────────────────────────────────────────────────

TABLE_LABELS = {
    "event_claims": "Claims",
    "event_episodes": "Episodes",
    "graph_edges": "Graph Edges",
    "beliefs": "Beliefs",
    "conversations": "Conversations",
}


def _scan_changes(conn, conversation_id: str, find_text: str, replace_with: str):
    """Scan all text objects in a conversation for find_text matches.

    Returns list of ChangeItem dicts.
    """
    changes = []

    # --- conversations.title ---
    convo = conn.execute(
        "SELECT id, title FROM conversations WHERE id = ?",
        (conversation_id,),
    ).fetchone()
    if convo and convo["title"]:
        new_val, ch_list = register_aware_replace(
            convo["title"], find_text, replace_with
        )
        if ch_list:
            worst = min(
                (c.confidence.value for c in ch_list),
                key=lambda x: {"high": 0, "medium": 1, "skipped": 2}[x],
            )
            changes.append(ChangeItem(
                change_id=f"convo_{conversation_id}_title",
                table="conversations",
                row_id=conversation_id,
                field="title",
                before=convo["title"],
                after=new_val,
                confidence=worst,
                register=ch_list[0].register.value if ch_list else "n/a",
            ))

    # --- event_claims: claim_text and subject_name ---
    claims = conn.execute(
        """SELECT id, claim_text, subject_name, text_user_edited
           FROM event_claims WHERE conversation_id = ?""",
        (conversation_id,),
    ).fetchall()

    for claim in claims:
        # claim_text
        if claim["claim_text"]:
            if claim["text_user_edited"]:
                # Check if there's a match but mark as skipped
                _, test_ch = register_aware_replace(
                    claim["claim_text"], find_text, replace_with
                )
                if test_ch:
                    changes.append(ChangeItem(
                        change_id=f"claim_{claim['id']}_text",
                        table="event_claims",
                        row_id=claim["id"],
                        field="claim_text",
                        before=claim["claim_text"],
                        after=claim["claim_text"],
                        confidence="skipped",
                        register="n/a",
                        skipped=True,
                        skip_reason="User-edited text",
                    ))
            else:
                new_val, ch_list = register_aware_replace(
                    claim["claim_text"], find_text, replace_with
                )
                if ch_list:
                    worst = min(
                        (c.confidence.value for c in ch_list),
                        key=lambda x: {"high": 0, "medium": 1, "skipped": 2}[x],
                    )
                    changes.append(ChangeItem(
                        change_id=f"claim_{claim['id']}_text",
                        table="event_claims",
                        row_id=claim["id"],
                        field="claim_text",
                        before=claim["claim_text"],
                        after=new_val,
                        confidence=worst,
                        register=ch_list[0].register.value if ch_list else "n/a",
                    ))

        # subject_name (entity field)
        if claim["subject_name"]:
            new_val, ch_list = register_aware_replace(
                claim["subject_name"], find_text, replace_with,
                is_entity_field=True,
            )
            if ch_list:
                changes.append(ChangeItem(
                    change_id=f"claim_{claim['id']}_subject",
                    table="event_claims",
                    row_id=claim["id"],
                    field="subject_name",
                    before=claim["subject_name"],
                    after=new_val,
                    confidence="high",
                    register="full",
                ))

    # --- event_episodes: title, summary ---
    episodes = conn.execute(
        "SELECT id, title, summary FROM event_episodes WHERE conversation_id = ?",
        (conversation_id,),
    ).fetchall()

    for ep in episodes:
        for field_name in ("title", "summary"):
            val = ep[field_name]
            if not val:
                continue
            new_val, ch_list = register_aware_replace(val, find_text, replace_with)
            if ch_list:
                worst = min(
                    (c.confidence.value for c in ch_list),
                    key=lambda x: {"high": 0, "medium": 1, "skipped": 2}[x],
                )
                changes.append(ChangeItem(
                    change_id=f"episode_{ep['id']}_{field_name}",
                    table="event_episodes",
                    row_id=ep["id"],
                    field=field_name,
                    before=val,
                    after=new_val,
                    confidence=worst,
                    register=ch_list[0].register.value if ch_list else "n/a",
                ))

    # --- graph_edges: from_entity, to_entity, notes ---
    edges = conn.execute(
        """SELECT id, from_entity, to_entity, notes
           FROM graph_edges WHERE source_conversation_id = ?""",
        (conversation_id,),
    ).fetchall()

    for edge in edges:
        for field_name, is_ent in [
            ("from_entity", True), ("to_entity", True), ("notes", False)
        ]:
            val = edge[field_name]
            if not val:
                continue
            new_val, ch_list = register_aware_replace(
                val, find_text, replace_with, is_entity_field=is_ent
            )
            if ch_list:
                worst = min(
                    (c.confidence.value for c in ch_list),
                    key=lambda x: {"high": 0, "medium": 1, "skipped": 2}[x],
                )
                changes.append(ChangeItem(
                    change_id=f"edge_{edge['id']}_{field_name}",
                    table="graph_edges",
                    row_id=edge["id"],
                    field=field_name,
                    before=val,
                    after=new_val,
                    confidence=worst,
                    register=ch_list[0].register.value if ch_list else "n/a",
                ))

    # --- beliefs: belief_summary (via belief_evidence join) ---
    beliefs = conn.execute(
        """SELECT DISTINCT b.id, b.belief_summary
           FROM beliefs b
           JOIN belief_evidence be ON be.belief_id = b.id
           JOIN event_claims ec ON be.claim_id = ec.id
           WHERE ec.conversation_id = ?
             AND b.belief_summary IS NOT NULL""",
        (conversation_id,),
    ).fetchall()

    for belief in beliefs:
        new_val, ch_list = register_aware_replace(
            belief["belief_summary"], find_text, replace_with
        )
        if ch_list:
            worst = min(
                (c.confidence.value for c in ch_list),
                key=lambda x: {"high": 0, "medium": 1, "skipped": 2}[x],
            )
            changes.append(ChangeItem(
                change_id=f"belief_{belief['id']}_summary",
                table="beliefs",
                row_id=belief["id"],
                field="belief_summary",
                before=belief["belief_summary"],
                after=new_val,
                confidence=worst,
                register=ch_list[0].register.value if ch_list else "n/a",
            ))

    return changes


# ── Preview Endpoint ───────────────────────────────────────────

@router.post("/preview")
def preview_text_replace(request: PreviewRequest):
    """Preview all text replacements within a single conversation."""
    find_text = request.find_text.strip()
    replace_with = request.replace_with.strip()

    if not find_text:
        raise HTTPException(400, "find_text cannot be empty")
    if not replace_with:
        raise HTTPException(400, "replace_with cannot be empty")
    if find_text.lower() == replace_with.lower():
        raise HTTPException(400, "find_text and replace_with are the same")

    conn = get_connection()
    try:
        convo = conn.execute(
            "SELECT id FROM conversations WHERE id = ?",
            (request.conversation_id,),
        ).fetchone()
        if not convo:
            raise HTTPException(404, "Conversation not found")

        changes = _scan_changes(conn, request.conversation_id, find_text, replace_with)

        # Build summary
        by_table = {}
        high = medium = skipped = 0
        for c in changes:
            by_table[c.table] = by_table.get(c.table, 0) + 1
            if c.confidence == "high":
                high += 1
            elif c.confidence == "medium":
                medium += 1
            elif c.skipped:
                skipped += 1

        return {
            "conversation_id": request.conversation_id,
            "find_text": find_text,
            "replace_with": replace_with,
            "changes": [c.model_dump() for c in changes],
            "summary": {
                "total": len(changes),
                "high_confidence": high,
                "medium_confidence": medium,
                "skipped": skipped,
                "by_table": by_table,
            },
        }
    finally:
        conn.close()


# ── Apply Endpoint ─────────────────────────────────────────────

@router.post("/apply")
def apply_text_replace(request: ApplyRequest):
    """Apply user-approved text replacements within a single conversation."""
    find_text = request.find_text.strip()
    replace_with = request.replace_with.strip()

    if not find_text or not replace_with:
        raise HTTPException(400, "find_text and replace_with required")
    if not request.change_ids:
        raise HTTPException(400, "No changes selected")

    # Build lookup for edited changes
    edited_map = {}
    for ec in request.edited_changes:
        edited_map[ec["id"]] = ec["custom_text"]

    conn = get_connection()
    try:
        convo = conn.execute(
            "SELECT id FROM conversations WHERE id = ?",
            (request.conversation_id,),
        ).fetchone()
        if not convo:
            raise HTTPException(404, "Conversation not found")

        # Re-scan to get fresh state
        changes = _scan_changes(conn, request.conversation_id, find_text, replace_with)
        change_map = {c.change_id: c for c in changes}

        approved_ids = set(request.change_ids)
        applied = 0
        skipped = 0
        re_embed_items_list = []
        belief_ids_affected = set()

        for change_id in approved_ids:
            change = change_map.get(change_id)
            if not change or change.skipped:
                skipped += 1
                continue

            # Determine final replacement text
            final_text = edited_map.get(change_id, change.after)

            # Apply the UPDATE
            if change.table == "conversations":
                conn.execute(
                    "UPDATE conversations SET title = ? WHERE id = ?",
                    (final_text, change.row_id),
                )
            elif change.table == "event_claims":
                if change.field == "claim_text":
                    conn.execute(
                        "UPDATE event_claims SET claim_text = ?, text_user_edited = 1 WHERE id = ?",
                        (final_text, change.row_id),
                    )
                    # Queue for re-embedding
                    re_embed_items_list.append({
                        "source_type": "claim",
                        "source_id": change.row_id,
                        "conversation_id": request.conversation_id,
                        "new_text": final_text,
                        "contact_id": None,
                    })
                elif change.field == "subject_name":
                    conn.execute(
                        "UPDATE event_claims SET subject_name = ? WHERE id = ?",
                        (final_text, change.row_id),
                    )
            elif change.table == "event_episodes":
                conn.execute(
                    f"UPDATE event_episodes SET {change.field} = ? WHERE id = ?",
                    (final_text, change.row_id),
                )
                if change.field in ("title", "summary"):
                    re_embed_items_list.append({
                        "source_type": "episode",
                        "source_id": change.row_id,
                        "conversation_id": request.conversation_id,
                        "new_text": final_text,
                        "contact_id": None,
                    })
            elif change.table == "graph_edges":
                conn.execute(
                    f"UPDATE graph_edges SET {change.field} = ? WHERE id = ?",
                    (final_text, change.row_id),
                )
            elif change.table == "beliefs":
                conn.execute(
                    "UPDATE beliefs SET belief_summary = ?, status = 'under_review' WHERE id = ?",
                    (final_text, change.row_id),
                )
                belief_ids_affected.add(change.row_id)

            applied += 1

        # Log correction event
        if applied > 0:
            conn.execute(
                """INSERT INTO correction_events
                   (id, conversation_id, error_type, old_value,
                    new_value, correction_source)
                   VALUES (?, ?, 'name_transcription', ?, ?, 'text_replace_cascade')""",
                (
                    str(uuid.uuid4()),
                    request.conversation_id,
                    find_text,
                    replace_with,
                ),
            )

        conn.commit()

        # Re-embed affected items (after commit)
        re_embedded = 0
        if re_embed_items_list:
            try:
                from sauron.embeddings.embedder import re_embed_items
                re_embedded = re_embed_items(re_embed_items_list)
            except Exception:
                logger.exception("Re-embedding failed (non-fatal)")

        logger.info(
            "[%s] Text replace cascade: applied=%d skipped=%d re_embedded=%d "
            "beliefs_affected=%d find='%s' replace='%s'",
            request.conversation_id[:8], applied, skipped, re_embedded,
            len(belief_ids_affected), find_text, replace_with,
        )

        return {
            "applied": applied,
            "skipped": skipped,
            "re_embedded": re_embedded,
            "beliefs_affected": len(belief_ids_affected),
        }

    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        logger.exception("Text replace apply failed")
        raise HTTPException(500, "Apply failed")
    finally:
        conn.close()
