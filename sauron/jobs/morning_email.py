"""
sauron/jobs/morning_email.py

Morning intelligence email — generates a comprehensive daily brief and
sends it via SMTP.  Designed to be called by APScheduler or a cron-style
trigger at 6:30 AM local time.

FIXED: Column names aligned to actual DB schema:
  - conversations has no title or speaker_count columns
    -> use manual_note or generate label from context_classification + source
    -> compute speaker_count from transcripts if needed
  - vocal_features stores actual values (pitch_mean, jitter, etc.) per row,
    not speaker/feature_name/baseline_deviation columns
    -> compare against vocal_baselines table for alerts
  - unified_contacts uses canonical_name, not display_name
  - transcripts uses speaker_id, not speaker_contact_id
"""

from __future__ import annotations

import base64
import json
import logging
import os
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Optional

from sauron.config import MORNING_EMAIL_RECIPIENT, GOOGLE_CALENDAR_ID
from sauron.db.connection import get_connection

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Colour palette (inline CSS, email-safe)
# ---------------------------------------------------------------------------
_BG = "#0a0f1a"
_CARD_BG = "#111827"
_TEXT = "#e5e7eb"
_HEADING = "#ffffff"
_ACCENT_BLUE = "#3b82f6"
_ACCENT_RED = "#ef4444"
_ACCENT_ORANGE = "#f59e0b"
_ACCENT_GREEN = "#22c55e"
_MUTED = "#9ca3af"
_BORDER = "#1f2937"


# ---------------------------------------------------------------------------
# Calendar integration (graceful fallback)
# ---------------------------------------------------------------------------


def _fetch_todays_calendar_events() -> list[dict]:
    """Return today's Google Calendar events, or an empty list if the
    Google API client is not configured."""
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds_path = os.environ.get(
            "GOOGLE_CALENDAR_CREDENTIALS",
            os.path.expanduser("~/.config/sauron/calendar_credentials.json"),
        )
        token_path = os.environ.get(
            "GOOGLE_CALENDAR_TOKEN",
            os.path.expanduser("~/.config/sauron/calendar_token.json"),
        )

        if not os.path.exists(token_path):
            logger.info("Calendar token not found at %s — skipping.", token_path)
            return []


        import json as _json

        with open(token_path) as f:
            token_data = _json.load(f)
        creds = Credentials.from_authorized_user_info(token_data)

        service = build("calendar", "v3", credentials=creds)

        now = datetime.utcnow()
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)

        calendar_id = GOOGLE_CALENDAR_ID or "primary"
        events_result = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=start_of_day.isoformat() + "Z",
                timeMax=end_of_day.isoformat() + "Z",
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = events_result.get("items", [])

        parsed: list[dict] = []
        for ev in events:
            start_raw = ev.get("start", {})
            start_str = start_raw.get("dateTime", start_raw.get("date", ""))
            attendees = [
                a.get("email", "") for a in ev.get("attendees", [])
            ]
            parsed.append(
                {
                    "summary": ev.get("summary", "(no title)"),
                    "start": start_str,
                    "attendees": attendees,
                    "location": ev.get("location", ""),
                    "hangout_link": ev.get("hangoutLink", ""),
                }
            )
        return parsed

    except Exception as exc:
        logger.warning("Calendar fetch failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Data gathering helpers
# ---------------------------------------------------------------------------


def _yesterday_range() -> tuple[str, str]:
    """Return (start, end) ISO strings for yesterday 00:00 to 23:59:59."""
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today - timedelta(days=1)
    yesterday_end = today - timedelta(seconds=1)
    return yesterday_start.isoformat(), yesterday_end.isoformat()


def _conversation_label(row: dict) -> str:
    """Generate a display label for a conversation.

    conversations has no 'title' column.  Use manual_note if available,
    otherwise build a label from context_classification + source, or
    fall back to the first 8 chars of the ID.
    """
    if row.get("manual_note"):
        return row["manual_note"]
    parts = []
    if row.get("context_classification"):
        parts.append(row["context_classification"].replace("_", " ").title())
    if row.get("source"):
        parts.append(f"({row['source']})")
    if parts:
        return " ".join(parts)
    return row["id"][:8]


def _get_yesterdays_conversations(conn) -> list[dict]:
    start, end = _yesterday_range()
    rows = conn.execute(
        """
        SELECT id, manual_note, source, context_classification,
               duration_seconds, processing_status, created_at
        FROM conversations
        WHERE created_at >= ? AND created_at <= ?
        ORDER BY created_at
        """,
        (start, end),
    ).fetchall()
    return [dict(r) for r in rows]


def _get_conversation_summaries(conn, conversation_ids: list[str]) -> dict[str, str]:
    """Map conversation_id -> summary text from the latest extraction."""
    summaries: dict[str, str] = {}
    for cid in conversation_ids:
        row = conn.execute(
            """
            SELECT extraction_json FROM extractions
            WHERE conversation_id = ?
            ORDER BY pass_number DESC LIMIT 1
            """,
            (cid,),
        ).fetchone()
        if row:
            try:
                data = json.loads(row["extraction_json"])
                summaries[cid] = (
                    data.get("summary")
                    or data.get("conversation_summary")
                    or ""
                )
            except (json.JSONDecodeError, TypeError):
                pass
    return summaries


def _get_action_items(conn, conversation_ids: list[str]) -> list[dict]:
    """Extract commitments and follow-ups from yesterday's extractions."""
    items: list[dict] = []
    for cid in conversation_ids:
        row = conn.execute(
            """
            SELECT extraction_json FROM extractions
            WHERE conversation_id = ?
            ORDER BY pass_number DESC LIMIT 1
            """,
            (cid,),
        ).fetchone()
        if not row:
            continue
        try:
            data = json.loads(row["extraction_json"])
        except (json.JSONDecodeError, TypeError):
            continue

        for key in ("my_commitments", "contact_commitments", "follow_ups", "follow_up_items"):
            entries = data.get(key, [])
            if not isinstance(entries, list):
                continue
            for entry in entries:
                text = entry if isinstance(entry, str) else (
                    entry.get("description") or entry.get("text") or str(entry)
                )
                items.append(
                    {
                        "type": key.replace("_", " ").title(),
                        "text": text,
                        "conversation_id": cid,
                    }
                )
    return items


def _get_triage_items(conn) -> list[dict]:
    """Conversations completed but not yet reviewed/corrected."""
    rows = conn.execute(
        """
        SELECT c.id, c.manual_note, c.source, c.context_classification,
               c.created_at
        FROM conversations c
        WHERE c.processing_status = 'completed'
          AND c.id NOT IN (
              SELECT DISTINCT conversation_id FROM extraction_corrections
          )
        ORDER BY c.created_at DESC
        LIMIT 20
        """,
    ).fetchall()
    return [dict(r) for r in rows]


def _get_performance_stats(conn) -> dict[str, Any]:
    """Last 7 days of personal_performance aggregated."""
    seven_days_ago = (datetime.now() - timedelta(days=7)).isoformat()
    rows = conn.execute(
        """
        SELECT
            AVG(talk_time_ratio) AS avg_talk_ratio,
            AVG(jitter_vs_baseline) AS avg_jitter,
            COUNT(*) AS session_count
        FROM personal_performance
        WHERE created_at >= ?
        """,
        (seven_days_ago,),
    ).fetchone()
    if rows and rows["session_count"]:
        return {
            "avg_talk_ratio": round(rows["avg_talk_ratio"] or 0, 2),
            "avg_jitter": round(rows["avg_jitter"] or 0, 3),
            "session_count": rows["session_count"],
        }
    return {}


def _get_vocal_alerts(conn) -> list[dict]:
    """Recent vocal feature outliers from yesterday.

    The vocal_features table stores actual feature values (pitch_mean,
    jitter, shimmer, etc.) per row — there is no 'speaker', 'feature_name',
    or 'baseline_deviation' column.

    We compare yesterday's vocal_features against the vocal_baselines table
    for each speaker_id and flag significant deviations (>2 sigma).
    If no baselines exist, we return an empty list.
    """
    start, end = _yesterday_range()

    # Get yesterday's vocal features with speaker info
    rows = conn.execute(
        """
        SELECT vf.conversation_id, vf.speaker_id,
               vf.jitter, vf.shimmer, vf.pitch_mean, vf.hnr,
               vf.speaking_rate_wpm,
               uc.canonical_name AS speaker_name
        FROM vocal_features vf
        LEFT JOIN unified_contacts uc ON vf.speaker_id = uc.id
        WHERE vf.created_at >= ? AND vf.created_at <= ?
          AND vf.speaker_id IS NOT NULL
        ORDER BY vf.created_at DESC
        """,
        (start, end),
    ).fetchall()

    if not rows:
        return []

    # Load baselines for all speakers we saw yesterday
    speaker_ids = list({r["speaker_id"] for r in rows if r["speaker_id"]})
    baselines: dict[str, dict] = {}
    for sid in speaker_ids:
        bl = conn.execute(
            """
            SELECT pitch_mean, jitter, shimmer, hnr, speaking_rate_wpm,
                   pitch_std, sample_count
            FROM vocal_baselines
            WHERE contact_id = ?
            LIMIT 1
            """,
            (sid,),
        ).fetchone()
        if bl and bl["sample_count"] and bl["sample_count"] >= 3:
            baselines[sid] = dict(bl)

    if not baselines:
        return []

    # Compare features against baselines and collect alerts
    # We use pitch_std as a rough sigma proxy for pitch_mean; for jitter/shimmer
    # we flag if the value exceeds 2x the baseline value (simple heuristic).
    _FEATURES_TO_CHECK = ["jitter", "shimmer", "pitch_mean", "hnr"]
    alerts: list[dict] = []

    for r in rows:
        sid = r["speaker_id"]
        bl = baselines.get(sid)
        if not bl:
            continue
        speaker_name = r["speaker_name"] or sid[:8]

        for feat in _FEATURES_TO_CHECK:
            val = r[feat]
            bl_val = bl.get(feat)
            if val is None or bl_val is None or bl_val == 0:
                continue

            ratio = val / bl_val
            # Flag if >2x or <0.5x the baseline (rough 2-sigma proxy)
            if ratio > 2.0 or ratio < 0.5:
                deviation = ratio - 1.0  # how far off from baseline
                alerts.append({
                    "conversation_id": r["conversation_id"],
                    "speaker": speaker_name,
                    "feature_name": feat,
                    "value": val,
                    "baseline_value": bl_val,
                    "deviation_ratio": round(deviation, 2),
                })

    # Sort by magnitude of deviation, return top 10
    alerts.sort(key=lambda a: abs(a["deviation_ratio"]), reverse=True)
    return alerts[:10]


def _build_game_plan(conn, attendees: list[str]) -> list[dict]:
    """For each attendee, pull recent context for pre-meeting prep."""
    plans: list[dict] = []
    for email in attendees:
        # unified_contacts uses canonical_name, not display_name
        contact = conn.execute(
            "SELECT id, canonical_name FROM unified_contacts WHERE email = ? LIMIT 1",
            (email,),
        ).fetchone()
        if not contact:
            plans.append({"email": email, "name": email, "context": "No prior data."})
            continue

        cid = contact["id"]
        name = contact["canonical_name"] or email

        # Recent conversations — no title column, use manual_note
        # transcripts uses speaker_id, not speaker_contact_id
        recent = conn.execute(
            """
            SELECT DISTINCT c.manual_note, c.source, c.context_classification,
                   c.id, c.created_at
            FROM conversations c
            JOIN transcripts t ON t.conversation_id = c.id
            WHERE t.speaker_id = ?
            ORDER BY c.created_at DESC LIMIT 3
            """,
            (cid,),
        ).fetchall()
        recent_txt = "; ".join(
            f'{_conversation_label(dict(r))} ({r["created_at"][:10]})' for r in recent
        ) or "None"

        # Open commitments from extractions involving this contact
        # transcripts uses speaker_id, not speaker_contact_id
        open_items = conn.execute(
            """
            SELECT e.extraction_json FROM extractions e
            JOIN conversations c ON c.id = e.conversation_id
            JOIN transcripts t ON t.conversation_id = c.id
            WHERE t.speaker_id = ?
            ORDER BY e.created_at DESC LIMIT 5
            """,
            (cid,),
        ).fetchall()

        commitments: list[str] = []
        for row in open_items:
            try:
                data = json.loads(row["extraction_json"])
                for k in ("my_commitments", "contact_commitments", "follow_ups"):
                    for item in data.get(k, []):
                        txt = item if isinstance(item, str) else (
                            item.get("description") or item.get("text") or ""
                        )
                        if txt:
                            commitments.append(txt)
            except (json.JSONDecodeError, TypeError):
                pass

        commitments_txt = "; ".join(commitments[:5]) or "None"

        plans.append(
            {
                "email": email,
                "name": name,
                "recent_conversations": recent_txt,
                "open_commitments": commitments_txt,
            }
        )
    return plans


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------


def _html_wrap(title: str, body_sections: str) -> str:
    """Wrap section HTML in the full email document."""
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width"></head>
<body style="margin:0;padding:0;background-color:{_BG};font-family:
-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="background-color:{_BG};">
<tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="640" cellpadding="0" cellspacing="0"
       style="max-width:640px;width:100%;">

<!-- Header -->
<tr><td style="padding:20px 24px;background:{_CARD_BG};border-radius:12px 12px 0 0;
               border-bottom:2px solid {_ACCENT_BLUE};">
  <h1 style="margin:0;font-size:22px;color:{_HEADING};">
    Sauron Morning Brief
  </h1>
  <p style="margin:4px 0 0;font-size:13px;color:{_MUTED};">
    {title}
  </p>
</td></tr>

<!-- Body sections -->
{body_sections}

<!-- Footer -->
<tr><td style="padding:16px 24px;background:{_CARD_BG};border-radius:0 0 12px 12px;
               text-align:center;">
  <p style="margin:0;font-size:11px;color:{_MUTED};">
    Generated by Project Sauron &middot; Voice Intelligence System
  </p>
</td></tr>

</table>
</td></tr></table>
</body></html>"""


def _section(title: str, content_html: str, accent: str = _ACCENT_BLUE) -> str:
    """Render one card-style section."""
    return f"""\
<tr><td style="padding:12px 24px;background:{_CARD_BG};border-left:3px solid {accent};">
  <h2 style="margin:0 0 8px;font-size:16px;color:{accent};">{title}</h2>
  <div style="color:{_TEXT};font-size:14px;line-height:1.5;">
    {content_html}
  </div>
</td></tr>
<tr><td style="height:4px;background:{_BG};"></td></tr>"""


def _alert_card(text: str) -> str:
    return (
        f'<div style="background:#2d1215;border:1px solid {_ACCENT_RED};'
        f'border-radius:8px;padding:10px 14px;margin:4px 0;color:{_ACCENT_RED};'
        f'font-size:13px;">{text}</div>'
    )


def _blue_card(text: str) -> str:
    return (
        f'<div style="background:#0c1a2e;border:1px solid {_ACCENT_BLUE};'
        f'border-radius:8px;padding:10px 14px;margin:4px 0;color:{_TEXT};'
        f'font-size:13px;">{text}</div>'
    )


# ---------------------------------------------------------------------------
# Main generation
# ---------------------------------------------------------------------------


def generate_morning_brief() -> str:
    """Build the full morning brief HTML email."""
    conn = get_connection()
    now = datetime.now()
    title = now.strftime("%A, %B %d, %Y")

    sections: list[str] = []

    # ------------------------------------------------------------------
    # 1. Priority alerts — triage items needing attention
    # ------------------------------------------------------------------
    triage = _get_triage_items(conn)
    if triage:
        cards = "".join(
            _alert_card(
                f'<strong>{_conversation_label(t)}</strong> '
                f'&mdash; captured {t["created_at"][:16]}, not yet reviewed'
            )
            for t in triage[:5]
        )
        extra = (
            f'<p style="color:{_MUTED};font-size:12px;margin:6px 0 0;">'
            f"+{len(triage) - 5} more</p>"
            if len(triage) > 5
            else ""
        )
        sections.append(_section(
            f"Priority: {len(triage)} Conversations Need Review",
            cards + extra,
            _ACCENT_RED,
        ))

    # ------------------------------------------------------------------
    # 2. Vocal alerts
    # ------------------------------------------------------------------
    vocal_alerts = _get_vocal_alerts(conn)
    if vocal_alerts:
        lines = "".join(
            f'<div style="margin:2px 0;color:{_ACCENT_ORANGE};font-size:13px;">'
            f'<strong>{a["speaker"]}</strong>: {a["feature_name"]} '
            f'= {a["value"]:.3f} (baseline {a["baseline_value"]:.3f}, '
            f'{a["deviation_ratio"]:+.0%} off)</div>'
            for a in vocal_alerts
        )
        sections.append(_section("Vocal Alerts", lines, _ACCENT_ORANGE))

    # ------------------------------------------------------------------
    # 3. Yesterday's conversations
    # ------------------------------------------------------------------
    convos = _get_yesterdays_conversations(conn)
    if convos:
        total_dur = sum(c.get("duration_seconds") or 0 for c in convos)
        dur_str = f"{total_dur // 3600}h {(total_dur % 3600) // 60}m" if total_dur else "N/A"
        summaries = _get_conversation_summaries(conn, [c["id"] for c in convos])

        rows_html = ""
        for c in convos:
            summary = summaries.get(c["id"], "")
            summary_short = (summary[:120] + "...") if len(summary) > 120 else summary
            label = _conversation_label(c)
            rows_html += (
                f'<tr>'
                f'<td style="padding:6px 8px;border-bottom:1px solid {_BORDER};'
                f'color:{_TEXT};font-size:13px;">{label}</td>'
                f'<td style="padding:6px 8px;border-bottom:1px solid {_BORDER};'
                f'color:{_MUTED};font-size:12px;">{summary_short}</td>'
                f'</tr>'
            )
        table = (
            f'<p style="margin:0 0 8px;color:{_MUTED};font-size:13px;">'
            f'{len(convos)} conversations &middot; {dur_str} total</p>'
            f'<table width="100%" cellpadding="0" cellspacing="0"'
            f' style="border-collapse:collapse;">{rows_html}</table>'
        )
        sections.append(_section("Yesterday's Conversations", table))
    else:
        sections.append(_section(
            "Yesterday's Conversations",
            f'<p style="color:{_MUTED};">No conversations captured yesterday.</p>',
        ))

    # ------------------------------------------------------------------
    # 4. Today's calendar + game plans
    # ------------------------------------------------------------------
    events = _fetch_todays_calendar_events()
    if events:
        event_cards = ""
        for ev in events:
            start = ev["start"]
            if "T" in start:
                try:
                    t = datetime.fromisoformat(start.replace("Z", "+00:00"))
                    start = t.strftime("%I:%M %p")
                except ValueError:
                    pass

            event_cards += (
                f'<div style="margin:6px 0;padding:8px 12px;background:#0c1a2e;'
                f'border-radius:6px;border:1px solid {_BORDER};">'
                f'<strong style="color:{_HEADING};font-size:14px;">'
                f'{start} &mdash; {ev["summary"]}</strong>'
            )

            if ev.get("location"):
                event_cards += (
                    f'<div style="color:{_MUTED};font-size:12px;margin-top:2px;">'
                    f'{ev["location"]}</div>'
                )

            # Game plan for attendees
            if ev.get("attendees"):
                plans = _build_game_plan(conn, ev["attendees"])
                for p in plans:
                    if p.get("context") == "No prior data.":
                        continue
                    event_cards += _blue_card(
                        f'<strong>{p["name"]}</strong><br>'
                        f'Recent: {p.get("recent_conversations", "N/A")}<br>'
                        f'Open items: {p.get("open_commitments", "N/A")}'
                    )

            event_cards += "</div>"

        sections.append(_section(
            f"Today's Calendar ({len(events)} meetings)",
            event_cards,
            _ACCENT_BLUE,
        ))
    else:
        sections.append(_section(
            "Today's Calendar",
            f'<p style="color:{_MUTED};">Calendar not configured or no events today.</p>',
        ))

    # ------------------------------------------------------------------
    # 5. Action items from yesterday
    # ------------------------------------------------------------------
    if convos:
        action_items = _get_action_items(conn, [c["id"] for c in convos])
        if action_items:
            rows_html = ""
            for ai in action_items[:15]:
                text_short = (ai["text"][:100] + "...") if len(ai["text"]) > 100 else ai["text"]
                rows_html += (
                    f'<tr>'
                    f'<td style="padding:5px 8px;border-bottom:1px solid {_BORDER};'
                    f'color:{_ACCENT_ORANGE};font-size:12px;white-space:nowrap;">'
                    f'{ai["type"]}</td>'
                    f'<td style="padding:5px 8px;border-bottom:1px solid {_BORDER};'
                    f'color:{_TEXT};font-size:13px;">{text_short}</td>'
                    f'</tr>'
                )
            table = (
                f'<table width="100%" cellpadding="0" cellspacing="0"'
                f' style="border-collapse:collapse;">{rows_html}</table>'
            )
            if len(action_items) > 15:
                table += (
                    f'<p style="color:{_MUTED};font-size:12px;margin:6px 0 0;">'
                    f'+{len(action_items) - 15} more items</p>'
                )
            sections.append(_section("Action Items", table, _ACCENT_ORANGE))

    # ------------------------------------------------------------------
    # 6. Personal performance (7-day)
    # ------------------------------------------------------------------
    perf = _get_performance_stats(conn)
    if perf:
        talk_pct = f"{perf['avg_talk_ratio'] * 100:.0f}%" if perf.get("avg_talk_ratio") else "N/A"
        jitter = f"{perf['avg_jitter']:.3f}" if perf.get("avg_jitter") is not None else "N/A"
        perf_html = (
            f'<table cellpadding="0" cellspacing="0" style="border-collapse:collapse;">'
            f'<tr>'
            f'<td style="padding:8px 16px;text-align:center;">'
            f'<div style="font-size:24px;color:{_ACCENT_BLUE};font-weight:bold;">'
            f'{perf["session_count"]}</div>'
            f'<div style="font-size:11px;color:{_MUTED};">Sessions</div></td>'
            f'<td style="padding:8px 16px;text-align:center;">'
            f'<div style="font-size:24px;color:{_ACCENT_GREEN};font-weight:bold;">'
            f'{talk_pct}</div>'
            f'<div style="font-size:11px;color:{_MUTED};">Avg Talk Ratio</div></td>'
            f'<td style="padding:8px 16px;text-align:center;">'
            f'<div style="font-size:24px;color:{_ACCENT_ORANGE};font-weight:bold;">'
            f'{jitter}</div>'
            f'<div style="font-size:11px;color:{_MUTED};">Avg Jitter vs Baseline</div></td>'
            f'</tr></table>'
        )
        sections.append(_section("7-Day Performance", perf_html, _ACCENT_GREEN))

    # ------------------------------------------------------------------
    # Assemble
    # ------------------------------------------------------------------
    return _html_wrap(title, "\n".join(sections))


# ---------------------------------------------------------------------------
# Email sending
# ---------------------------------------------------------------------------


def send_morning_email(html_content: str) -> None:
    """Send the morning brief via Gmail API. Falls back to SMTP if OAuth not configured."""
    recipient = MORNING_EMAIL_RECIPIENT
    if not recipient:
        logger.warning("MORNING_EMAIL_RECIPIENT not set. Skipping email send.")
        return

    sender_email = os.environ.get("SMTP_USER", "stephen@stephenandrews.org")
    sender = f"Sauron <{sender_email}>"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Sauron Morning Brief \u2014 {datetime.now().strftime('%A, %B %d')}"
    msg["From"] = sender
    msg["To"] = recipient

    # Plain-text fallback
    plain = (
        "Your Sauron Morning Brief is ready. "
        "View this email in an HTML-capable client for the full report."
    )
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html_content, "html"))

    # Try Gmail API first (works with Google Workspace OAuth)
    token_path = os.path.expanduser("~/.config/sauron/calendar_token.json")
    if os.path.exists(token_path):
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            with open(token_path) as f:
                token_data = json.load(f)
            creds = Credentials.from_authorized_user_info(token_data)
            service = build("gmail", "v1", credentials=creds)

            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            service.users().messages().send(
                userId="me", body={"raw": raw}
            ).execute()
            logger.info("Morning brief sent to %s via Gmail API", recipient)
            return
        except Exception as exc:
            logger.warning("Gmail API send failed, trying SMTP: %s", exc)

    # Fallback: SMTP
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_password = os.environ.get("SMTP_PASSWORD")

    if not all([smtp_host, sender_email, smtp_password]):
        logger.error("Neither Gmail API nor SMTP configured. Cannot send email.")
        return

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(sender_email, smtp_password)
            server.sendmail(sender_email, [recipient], msg.as_string())
        logger.info("Morning brief sent to %s via SMTP", recipient)
    except Exception as exc:
        logger.error("Failed to send morning brief: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# Scheduler entry point
# ---------------------------------------------------------------------------


def run_morning_brief_job() -> None:
    """Generate and send the morning brief. Call from scheduler."""
    logger.info("Starting morning brief generation...")
    try:
        html = generate_morning_brief()
        send_morning_email(html)
        logger.info("Morning brief job completed.")
    except Exception as exc:
        logger.error("Morning brief job failed: %s", exc, exc_info=True)
