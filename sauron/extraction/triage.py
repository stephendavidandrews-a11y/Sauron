"""Pass 1: Haiku 4.5 Triage + Episode Segmentation.

Receives raw diarized transcript (no vocal data, no contact context).
Determines context classification, value assessment, AND segments the
conversation into topical episodes for downstream extraction.

Cost: ~$0.01/conversation
"""

import json
import logging

import anthropic

from sauron.config import TRIAGE_MODEL
from sauron.extraction.json_utils import extract_json
from sauron.extraction.schemas import TriageResult

logger = logging.getLogger(__name__)

TRIAGE_SYSTEM_PROMPT = """You are a conversation triage and segmentation system. You receive a diarized
transcript and must:
1. Quickly classify the conversation
2. Segment it into topical episodes (distinct topics or phases within the conversation)

Output valid JSON matching this schema exactly:
{
  "context_classification": "cftc_team | cftc_stakeholder | professional_network | personal | mixed | solo_brainstorm | solo_tasks | solo_debrief | solo_analysis | solo_reflection",
  "speaker_count": <int>,
  "speaker_hints": ["any names mentioned or identification clues"],
  "topic_tags": ["topic1", "topic2"],
  "value_assessment": "high | medium | low",
  "value_reasoning": "brief explanation",
  "summary": "2-3 sentence summary",
  "is_solo": true/false,
  "solo_mode": null or "note | tasks | debrief | journal | prep | general",
  "episodes": [
    {
      "title": "Short descriptive title",
      "start_time": <float seconds>,
      "end_time": <float seconds>,
      "episode_type": "small_talk | substantive | commitment | relationship_intel | logistics | other",
      "summary": "1-2 sentence summary of this episode"
    }
  ]
}

Classification rules:
- cftc_team: conversation between CFTC staff about work (regulatory, legal, policy)
- cftc_stakeholder: conversation with external regulatory stakeholders
- professional_network: networking, industry contacts, non-CFTC professional
- personal: friends, family, personal matters
- mixed: crosses categories
- solo_*: single speaker (Stephen talking to himself)

Value assessment:
- high: substantive discussion, action items, relationship dynamics, policy positions, commitments
- medium: useful information but routine (scheduling, brief check-ins with some content)
- low: ambient noise, pure logistics, greetings with no substance, background noise

Episode segmentation rules:
- Every conversation has at least one episode
- Look for topic shifts, mood changes, or natural conversation phases
- Small talk at start/end is its own episode
- Commitment exchanges (promises, deadlines) get their own episode
- Timestamps come from the [start-end] markers in the transcript
- Episode boundaries don't need to be exact — approximate is fine

If the transcript starts with "Hey Sauron" followed by a command word, set solo_mode accordingly:
- "Hey Sauron, note" → solo_mode: "note"
- "Hey Sauron, tasks" → solo_mode: "tasks"
- "Hey Sauron, debrief" → solo_mode: "debrief"
- "Hey Sauron, journal" → solo_mode: "journal"
- "Hey Sauron, prep" → solo_mode: "prep"
"""


def triage_conversation(
    transcript_text: str,
    amendment_context: str = "",
) -> tuple[TriageResult, object]:
    """Run Haiku triage + episode segmentation on a diarized transcript.

    Args:
        transcript_text: Formatted diarized transcript (SPEAKER_00: text...)
        amendment_context: Learned preferences to append to system prompt.

    Returns:
        (TriageResult with episodes, usage object)
    """
    client = anthropic.Anthropic(max_retries=2)

    system = TRIAGE_SYSTEM_PROMPT
    if amendment_context:
        system += f"\n\n{amendment_context}"

    logger.info("Running Haiku triage + episode segmentation...")
    response = client.messages.create(
        model=TRIAGE_MODEL,
        max_tokens=4096,
        system=system,
        messages=[
            {"role": "user", "content": f"Triage and segment this conversation transcript:\n\n{transcript_text}"}
        ],
    )

    raw_text = response.content[0].text.strip()
    json_text = extract_json(raw_text)

    result = TriageResult.model_validate_json(json_text)

    logger.info(
        f"Triage: {result.context_classification}, "
        f"value={result.value_assessment}, "
        f"speakers={result.speaker_count}, "
        f"episodes={len(result.episodes)}, "
        f"solo={result.is_solo}"
    )

    return result, response.usage


def should_run_deep_extraction(triage: TriageResult) -> bool:
    """Determine if a conversation warrants the full extraction passes.

    Skip Sonnet+Opus for low-value captures to save ~$0.17/conversation.
    """
    if triage.value_assessment == "low":
        return False
    # Always extract solo captures with explicit commands
    if triage.is_solo and triage.solo_mode in ("tasks", "debrief", "prep"):
        return True
    # Skip low-value solo without commands
    if triage.is_solo and triage.solo_mode == "general" and triage.value_assessment == "medium":
        return False
    return True


def generate_title(
    transcript_text: str | None = None,
    triage_result=None,
) -> str | None:
    """Generate a concise 5-8 word conversation title.

    Prefers transcript text (available earliest in pipeline). Enriches
    with triage data when available. Falls back gracefully.

    Args:
        transcript_text: Raw transcript (will use first ~500 words).
        triage_result: TriageResult or dict with summary/topics/episodes.

    Returns:
        Title string, or None on failure.
    """
    # Build context from whatever we have
    context_parts = []

    # Triage data enriches the prompt when available
    if triage_result is not None:
        if hasattr(triage_result, "summary"):
            summary = triage_result.summary
            topics = getattr(triage_result, "topic_tags", []) or []
            hints = getattr(triage_result, "speaker_hints", []) or []
            episodes = getattr(triage_result, "episodes", []) or []
        elif isinstance(triage_result, dict):
            summary = triage_result.get("summary", "")
            topics = triage_result.get("topic_tags", []) or []
            hints = triage_result.get("speaker_hints", []) or []
            episodes = triage_result.get("episodes", []) or []
        else:
            summary = ""
            topics = hints = episodes = []

        if summary:
            context_parts.append(f"Summary: {summary}")
        if topics:
            context_parts.append("Topics: " + ", ".join(topics[:5]))
        if hints:
            context_parts.append("Speakers: " + ", ".join(hints[:3]))

        episode_titles = []
        for ep in episodes[:2]:
            if hasattr(ep, "title"):
                episode_titles.append(ep.title)
            elif isinstance(ep, dict):
                episode_titles.append(ep.get("title", ""))
        if episode_titles:
            context_parts.append("Episodes: " + ", ".join(episode_titles))

    # Transcript snippet — primary source, always available early
    snippet = ""
    if transcript_text and len(transcript_text.strip()) >= 20:
        words = transcript_text.split()
        snippet = " ".join(words[:500])
        if len(words) > 500:
            snippet += "..."
        context_parts.append(f"Transcript excerpt:\n{snippet}")

    if not context_parts:
        return None

    context = "\n".join(context_parts)

    try:
        client = anthropic.Anthropic(max_retries=2)
        response = client.messages.create(
            model=TRIAGE_MODEL,
            max_tokens=30,
            messages=[{
                "role": "user",
                "content": (
                    "Generate a 5-8 word descriptive title for this conversation. "
                    "No quotes, no ending punctuation. The title should identify who "
                    "was involved (if known) and the main topic.\n\n"
                    "Examples:\n"
                    "- Catherine on Dodd-Frank implementation timeline\n"
                    "- Solo brainstorm on pipeline architecture\n"
                    "- Stephen and Weber discuss CFTC staffing\n"
                    "- Quick check-in about weekend plans\n"
                    "- Pi office chatter with background noise\n\n"
                    + context + "\n\nTitle:"
                )
            }],
        )
        title = response.content[0].text.strip().strip('"').strip("'").rstrip(".")
        if len(title) < 3 or len(title) > 100:
            logger.warning(f"Title generation returned unusual length ({len(title)}): {title}")
            return title[:100] if len(title) > 100 else None
        logger.info(f"Generated title: {title}")
        return title
    except Exception as e:
        logger.warning(f"Title generation failed: {e}")
        return None
