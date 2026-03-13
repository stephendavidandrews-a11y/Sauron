"""Contact rename API with downstream propagation.

Two-phase workflow:
  1. Preview: scan all entity-linked records, compute proposed changes
  2. Apply: execute user-approved changes, re-embed, save alias, log correction

Endpoints mounted under /graph prefix via main.py router registration.
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
router = APIRouter(prefix="/graph", tags=["rename"])


# ── Request / Response Models ──────────────────────────────────

class PreviewRenameRequest(BaseModel):
    new_name: str
    old_name_override: Optional[str] = None


class ApplyRenameRequest(BaseModel):
    new_name: str
    change_ids: list[str]
    old_name_override: Optional[str] = None


class ChangeItem(BaseModel):
    change_id: str
    table: str
    row_id: str
    field: str
    before: str
    after: str
    confidence: str
    register: str
    conversation_id: Optional[str] = None
    skipped: bool = False
    skip_reason: Optional[str] = None


# ── Preview Endpoint ───────────────────────────────────────────

@router.post("/contacts/{contact_id}/preview-rename")
def preview_rename(contact_id: str, request: PreviewRenameRequest):
    """Preview all changes that would result from renaming a contact."""
    conn = get_connection()
    try:
        contact = conn.execute(
            "SELECT id, canonical_name, is_confirmed FROM unified_contacts WHERE id = ?",
            (contact_id,),
        ).fetchone()
        if not contact:
            raise HTTPException(404, "Contact not found")

        old_name = request.old_name_override or contact["canonical_name"]
        new_name = request.new_name.strip()

        if not new_name:
            raise HTTPException(400, "new_name cannot be empty")
        if old_name.strip().lower() == new_name.lower():
            raise HTTPException(400, "new_name is the same as old_name")

        changes = []

        # --- Contact canonical_name ---
        changes.append(ChangeItem(
            change_id=f"contact_{contact_id}_name",
            table="unified_contacts",
            row_id=contact_id,
            field="canonical_name",
            before=contact["canonical_name"],
            after=new_name,
            confidence="high",
            register="full",
        ))

        # --- event_claims ---
        claims = conn.execute("""
            SELECT id, claim_text, subject_name, text_user_edited,
                   review_status, conversation_id
            FROM event_claims
            WHERE subject_entity_id = ?
              AND (review_status IS NULL OR review_status != 'dismissed')
        """, (contact_id,)).fetchall()

        for claim in claims:
            # subject_name (entity field)
            if claim["subject_name"]:
                new_subj, subj_changes = register_aware_replace(
                    claim["subject_name"], old_name, new_name, is_entity_field=True
                )
                if subj_changes:
                    changes.append(ChangeItem(
                        change_id=f"claim_{claim['id']}_subject",
                        table="event_claims",
                        row_id=claim["id"],
                        field="subject_name",
                        before=claim["subject_name"],
                        after=new_subj,
                        confidence="high",
                        register="full",
                        conversation_id=claim["conversation_id"],
                    ))

            # claim_text (free text)
            if claim["claim_text"]:
                if claim["text_user_edited"]:
                    # Check if old name is even in the text
                    _, test_changes = register_aware_replace(
                        claim["claim_text"], old_name, new_name
                    )
                    if test_changes:
                        changes.append(ChangeItem(
                            change_id=f"claim_{claim['id']}_text",
                            table="event_claims",
                            row_id=claim["id"],
                            field="claim_text",
                            before=claim["claim_text"],
                            after="(user-edited, not auto-replaced)",
                            confidence="skipped",
                            register="n/a",
                            conversation_id=claim["conversation_id"],
                            skipped=True,
                            skip_reason="user_edited",
                        ))
                else:
                    new_text, text_changes = register_aware_replace(
                        claim["claim_text"], old_name, new_name
                    )
                    if text_changes:
                        # Use the lowest confidence from any change in this text
                        worst_conf = min(
                            (c.confidence.value for c in text_changes),
                            key=lambda x: {"high": 0, "medium": 1, "skipped": 2}[x],
                        )
                        changes.append(ChangeItem(
                            change_id=f"claim_{claim['id']}_text",
                            table="event_claims",
                            row_id=claim["id"],
                            field="claim_text",
                            before=claim["claim_text"],
                            after=new_text,
                            confidence=worst_conf,
                            register=text_changes[0].register.value,
                            conversation_id=claim["conversation_id"],
                        ))

        # --- event_episodes ---
        # Find episodes in conversations that mention this entity
        conv_ids = list({c["conversation_id"] for c in claims if c["conversation_id"]})
        if conv_ids:
            placeholders = ",".join("?" for _ in conv_ids)
            episodes = conn.execute(f"""
                SELECT id, title, summary, conversation_id
                FROM event_episodes
                WHERE conversation_id IN ({placeholders})
            """, conv_ids).fetchall()

            for ep in episodes:
                for field_name in ("title", "summary"):
                    val = ep[field_name]
                    if not val:
                        continue
                    new_val, ep_changes = register_aware_replace(val, old_name, new_name)
                    if ep_changes:
                        worst_conf = min(
                            (c.confidence.value for c in ep_changes),
                            key=lambda x: {"high": 0, "medium": 1, "skipped": 2}[x],
                        )
                        changes.append(ChangeItem(
                            change_id=f"episode_{ep['id']}_{field_name}",
                            table="event_episodes",
                            row_id=ep["id"],
                            field=field_name,
                            before=val,
                            after=new_val,
                            confidence=worst_conf,
                            register=ep_changes[0].register.value,
                            conversation_id=ep["conversation_id"],
                        ))

        # --- graph_edges ---
        edges = conn.execute("""
            SELECT id, from_entity, from_type, to_entity, to_type, notes,
                   source_conversation_id
            FROM graph_edges
            WHERE from_entity = ? OR to_entity = ?
        """, (old_name.strip(), old_name.strip())).fetchall()

        # Also find fuzzy matches on from_entity/to_entity
        all_edges = conn.execute("""
            SELECT id, from_entity, from_type, to_entity, to_type, notes,
                   source_conversation_id
            FROM graph_edges
        """).fetchall()

        seen_edge_ids = {e["id"] for e in edges}
        for e in all_edges:
            if e["id"] in seen_edge_ids:
                continue
            from_new, from_ch = register_aware_replace(
                e["from_entity"], old_name, new_name, is_entity_field=True
            )
            to_new, to_ch = register_aware_replace(
                e["to_entity"], old_name, new_name, is_entity_field=True
            )
            if from_ch or to_ch:
                edges = list(edges) + [e]
                seen_edge_ids.add(e["id"])

        for edge in edges:
            for field_name, is_ent in [
                ("from_entity", True), ("to_entity", True), ("notes", False)
            ]:
                val = edge[field_name]
                if not val:
                    continue
                new_val, edge_changes = register_aware_replace(
                    val, old_name, new_name, is_entity_field=is_ent
                )
                if edge_changes:
                    worst_conf = min(
                        (c.confidence.value for c in edge_changes),
                        key=lambda x: {"high": 0, "medium": 1, "skipped": 2}[x],
                    )
                    changes.append(ChangeItem(
                        change_id=f"edge_{edge['id']}_{field_name}",
                        table="graph_edges",
                        row_id=edge["id"],
                        field=field_name,
                        before=val,
                        after=new_val,
                        confidence=worst_conf,
                        register=edge_changes[0].register.value,
                        conversation_id=edge["source_conversation_id"],
                    ))

        # --- beliefs ---
        beliefs = conn.execute("""
            SELECT id, belief_summary, entity_id
            FROM beliefs
            WHERE entity_id = ?
        """, (contact_id,)).fetchall()

        # Also scan all beliefs for text matches
        all_beliefs = conn.execute(
            "SELECT id, belief_summary, entity_id FROM beliefs"
        ).fetchall()
        seen_belief_ids = {b["id"] for b in beliefs}
        for b in all_beliefs:
            if b["id"] in seen_belief_ids and b["belief_summary"]:
                continue
            if b["belief_summary"]:
                _, test_ch = register_aware_replace(b["belief_summary"], old_name, new_name)
                if test_ch:
                    beliefs = list(beliefs) + [b]
                    seen_belief_ids.add(b["id"])

        for belief in beliefs:
            if not belief["belief_summary"]:
                continue
            new_summary, b_changes = register_aware_replace(
                belief["belief_summary"], old_name, new_name
            )
            if b_changes:
                worst_conf = min(
                    (c.confidence.value for c in b_changes),
                    key=lambda x: {"high": 0, "medium": 1, "skipped": 2}[x],
                )
                changes.append(ChangeItem(
                    change_id=f"belief_{belief['id']}_summary",
                    table="beliefs",
                    row_id=belief["id"],
                    field="belief_summary",
                    before=belief["belief_summary"],
                    after=new_summary,
                    confidence=worst_conf,
                    register=b_changes[0].register.value,
                ))

        # --- conversations.title ---
        if conv_ids:
            convos = conn.execute(f"""
                SELECT id, title FROM conversations
                WHERE id IN ({",".join("?" for _ in conv_ids)})
            """, conv_ids).fetchall()
            for convo in convos:
                if not convo["title"]:
                    continue
                new_title, t_changes = register_aware_replace(
                    convo["title"], old_name, new_name
                )
                if t_changes:
                    worst_conf = min(
                        (c.confidence.value for c in t_changes),
                        key=lambda x: {"high": 0, "medium": 1, "skipped": 2}[x],
                    )
                    changes.append(ChangeItem(
                        change_id=f"convo_{convo['id']}_title",
                        table="conversations",
                        row_id=convo["id"],
                        field="title",
                        before=convo["title"],
                        after=new_title,
                        confidence=worst_conf,
                        register=t_changes[0].register.value,
                        conversation_id=convo["id"],
                    ))

        # --- Summary ---
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
            "contact_id": contact_id,
            "old_name": old_name,
            "new_name": new_name,
            "changes": [c.dict() for c in changes],
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

@router.post("/contacts/{contact_id}/apply-rename")
def apply_rename(contact_id: str, request: ApplyRenameRequest):
    """Apply user-approved rename changes."""
    conn = get_connection()
    try:
        contact = conn.execute(
            "SELECT id, canonical_name, is_confirmed FROM unified_contacts WHERE id = ?",
            (contact_id,),
        ).fetchone()
        if not contact:
            raise HTTPException(404, "Contact not found")

        old_name = request.old_name_override or contact["canonical_name"]
        new_name = request.new_name.strip()
        approved_ids = set(request.change_ids)

        if not new_name:
            raise HTTPException(400, "new_name cannot be empty")

        applied = 0
        skipped = 0
        affected_claim_ids = set()
        affected_belief_ids = set()
        affected_episode_ids = set()

        # Re-run preview to get fresh state, then apply only approved changes
        preview = preview_rename(contact_id, PreviewRenameRequest(
            new_name=new_name, old_name_override=request.old_name_override
        ))

        change_map = {c["change_id"]: c for c in preview["changes"]}

        for change_id in approved_ids:
            if change_id not in change_map:
                skipped += 1
                continue

            c = change_map[change_id]
            if c["skipped"]:
                skipped += 1
                continue

            table = c["table"]
            row_id = c["row_id"]
            field = c["field"]
            new_val = c["after"]

            try:
                if table == "unified_contacts":
                    conn.execute(
                        "UPDATE unified_contacts SET canonical_name = ? WHERE id = ?",
                        (new_val, row_id),
                    )
                elif table == "event_claims":
                    conn.execute(
                        f"UPDATE event_claims SET {field} = ? WHERE id = ?",
                        (new_val, row_id),
                    )
                    affected_claim_ids.add(row_id)
                elif table == "event_episodes":
                    conn.execute(
                        f"UPDATE event_episodes SET {field} = ? WHERE id = ?",
                        (new_val, row_id),
                    )
                    affected_episode_ids.add(row_id)
                elif table == "graph_edges":
                    conn.execute(
                        f"UPDATE graph_edges SET {field} = ? WHERE id = ?",
                        (new_val, row_id),
                    )
                elif table == "beliefs":
                    conn.execute(
                        "UPDATE beliefs SET belief_summary = ?, status = 'under_review' WHERE id = ?",
                        (new_val, row_id),
                    )
                    affected_belief_ids.add(row_id)
                elif table == "conversations":
                    conn.execute(
                        "UPDATE conversations SET title = ? WHERE id = ?",
                        (new_val, row_id),
                    )
                applied += 1
            except Exception as e:
                logger.error(f"Failed to apply rename change {change_id}: {e}")
                skipped += 1

        # Save old name as alias
        alias_saved = False
        try:
            from sauron.extraction.alias_learner import learn_alias
            alias_saved = learn_alias(conn, contact_id, old_name, new_name)
        except Exception as e:
            logger.error(f"Failed to save alias: {e}")

        # Log correction event
        correction_id = str(uuid.uuid4())
        try:
            import json
            conn.execute("""
                INSERT INTO correction_events
                (id, conversation_id, error_type, old_value, new_value,
                 correction_source, created_at)
                VALUES (?, NULL, 'contact_renamed', ?, ?, 'rename_cascade', datetime('now'))
            """, (
                correction_id,
                json.dumps({"old_name": old_name, "change_count": applied}),
                json.dumps({"new_name": new_name, "tables": list({
                    c["table"] for cid, c in change_map.items() if cid in approved_ids
                })}),
            ))
        except Exception as e:
            logger.error(f"Failed to log correction event: {e}")

        conn.commit()

        # Post-commit: re-embed affected items
        re_embedded = 0
        try:
            from sauron.embeddings.embedder import re_embed_items
            items = []
            for claim_id in affected_claim_ids:
                claim = conn.execute(
                    "SELECT claim_text, subject_name, claim_type FROM event_claims WHERE id = ?",
                    (claim_id,),
                ).fetchone()
                if claim and claim["claim_text"]:
                    text = f"{claim['claim_type'] or 'claim'}: {claim['claim_text']}"
                    if claim["subject_name"]:
                        text += f" (about {claim['subject_name']})"
                    conv_id = conn.execute(
                        "SELECT conversation_id FROM event_claims WHERE id = ?",
                        (claim_id,),
                    ).fetchone()
                    items.append({
                        "source_type": "claim",
                        "source_id": claim_id,
                        "conversation_id": conv_id["conversation_id"] if conv_id else None,
                        "new_text": text,
                        "contact_id": contact_id,
                    })

            for belief_id in affected_belief_ids:
                belief = conn.execute(
                    "SELECT belief_summary, entity_type FROM beliefs WHERE id = ?",
                    (belief_id,),
                ).fetchone()
                if belief and belief["belief_summary"]:
                    items.append({
                        "source_type": "belief",
                        "source_id": belief_id,
                        "conversation_id": None,
                        "new_text": f"belief ({belief['entity_type']}): {belief['belief_summary']}",
                        "contact_id": contact_id,
                    })

            if items:
                re_embedded = re_embed_items(items)
        except Exception as e:
            logger.error(f"Re-embedding failed: {e}")

        # Queue belief re-synthesis
        beliefs_queued = 0
        try:
            from sauron.learning.resynthesize import queue_resynthesis
            for belief_id in affected_belief_ids:
                queue_resynthesis(belief_id, trigger_correction_id=correction_id)
                beliefs_queued += 1
        except Exception as e:
            logger.error(f"Belief re-synthesis queueing failed: {e}")

        return {
            "status": "ok",
            "applied": applied,
            "skipped": skipped,
            "re_embedded": re_embedded,
            "beliefs_queued_for_resynthesis": beliefs_queued,
            "alias_saved": old_name if alias_saved else None,
            "correction_event_id": correction_id,
        }
    finally:
        conn.close()
