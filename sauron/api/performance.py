"""Personal performance tracking API endpoints."""

from datetime import date, timedelta

from fastapi import APIRouter

from sauron.db.connection import get_connection

router = APIRouter(prefix="/performance", tags=["performance"])


@router.get("/weekly")
def get_weekly_summary():
    """Get personal performance summary for the current week."""
    today = date.today()
    week_start = (today - timedelta(days=today.weekday())).isoformat()
    week_end = today.isoformat()

    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT * FROM personal_performance
               WHERE date >= ? AND date <= ?
               ORDER BY date""",
            (week_start, week_end),
        ).fetchall()

        if not rows:
            return {"week": f"{week_start} to {week_end}", "data": [], "summary": None}

        data = [dict(r) for r in rows]

        # Compute weekly averages
        talk_ratios = [r["talk_time_ratio"] for r in rows if r["talk_time_ratio"]]
        interruptions = [r["interruption_count"] for r in rows if r["interruption_count"]]
        jitters = [r["jitter"] for r in rows if r["jitter"]]
        engagement = [r["engagement_score"] for r in rows if r["engagement_score"]]

        summary = {
            "conversation_count": len(data),
            "avg_talk_time_ratio": sum(talk_ratios) / len(talk_ratios) if talk_ratios else None,
            "total_interruptions": sum(interruptions) if interruptions else 0,
            "avg_jitter": sum(jitters) / len(jitters) if jitters else None,
            "avg_engagement": sum(engagement) / len(engagement) if engagement else None,
        }

        return {"week": f"{week_start} to {week_end}", "data": data, "summary": summary}
    finally:
        conn.close()


@router.get("/trends")
def get_performance_trends(weeks: int = 8):
    """Get longitudinal performance data across multiple weeks."""
    today = date.today()
    start_date = (today - timedelta(weeks=weeks)).isoformat()

    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT
                 strftime('%Y-W%W', date) as week,
                 COUNT(*) as conversation_count,
                 AVG(talk_time_ratio) as avg_talk_ratio,
                 SUM(interruption_count) as total_interruptions,
                 AVG(jitter) as avg_jitter,
                 AVG(engagement_score) as avg_engagement,
                 AVG(pitch_authority_score) as avg_pitch_authority
               FROM personal_performance
               WHERE date >= ?
               GROUP BY strftime('%Y-W%W', date)
               ORDER BY week""",
            (start_date,),
        ).fetchall()

        return [dict(r) for r in rows]
    finally:
        conn.close()
