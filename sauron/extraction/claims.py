import hashlib
"""Pass 2: Sonnet 4.6 Claims Extraction.

Receives: diarized transcript + episode boundaries from Haiku.
Produces: atomic claims with evidence spans, memory writes, new contacts.

Internally staged prompt: Candidate Detection -> Normalization -> Filter.
Episodes are processed in BATCHES of 2-3 with concurrent API calls.
Each batch gets a transcript slice (by speaker turn boundaries) with
one episode of buffer on each side for context. A hard post-filter
drops claims from context episodes.

This is the HARD BOUNDARY in the architecture. Claims are extracted
directly from transcripts. Beliefs are synthesized LATER from claims.
Do NOT extract beliefs or recommendations here.

V8: Added participant roster from speaker_map + name disambiguation rules.
"""

import asyncio
import json
import logging
import re

import anthropic

from sauron.config import CLAIMS_MODEL
from sauron.extraction.json_utils import extract_json
from sauron.extraction.claims_base import build_voice_claims_prompt
from sauron.extraction.schemas import ClaimsResult, Episode

logger = logging.getLogger(__name__)

# Max episodes per batch — keeps JSON output under ~300 lines
EPISODES_PER_BATCH = 3

# Max concurrent API calls
MAX_CONCURRENCY = 3

CLAIMS_SYSTEM_PROMPT = build_voice_claims_prompt()


# ── Participant roster builder ──────────────────────────────────

def _build_participant_roster(speaker_map: dict | None) -> str:
    """Build a structured participant roster from speaker_map.

    Looks up each contact_id in unified_contacts to get their full name,
    aliases, and relationship context. Returns a formatted string to
    inject into the extraction prompt.

    Args:
        speaker_map: Dict mapping speaker labels (e.g., "SPEAKER_00")
                     to unified_contacts IDs, or None.

    Returns:
        Formatted participant roster string, or empty string if no map.
    """
    if not speaker_map:
        return ""

    from sauron.db.connection import get_connection

    conn = get_connection()
    try:
        # Look up all contact IDs from the speaker map
        contact_ids = list(set(speaker_map.values()))
        if not contact_ids:
            return ""

        placeholders = ",".join("?" * len(contact_ids))
        contacts = conn.execute(
            f"SELECT id, canonical_name, aliases, relationships FROM unified_contacts WHERE id IN ({placeholders})",
            contact_ids,
        ).fetchall()

        contact_lookup = {dict(c)["id"]: dict(c) for c in contacts}

        # Build the roster
        lines = []
        lines.append("## Participant Roster")
        lines.append("The following people have been identified in this conversation:")
        lines.append("")

        # Track names for disambiguation warnings
        first_names_seen = {}  # first_name -> list of full names

        for speaker_label, contact_id in sorted(speaker_map.items()):
            contact = contact_lookup.get(contact_id)
            if not contact:
                lines.append(f"- {speaker_label}: Unknown (unidentified speaker)")
                continue

            full_name = contact["canonical_name"]
            first_name = full_name.split()[0] if full_name else speaker_label
            first_names_seen.setdefault(first_name, []).append(full_name)

            # Build participant entry
            entry = f"- {speaker_label} → **{full_name}**"

            # Add aliases if present
            aliases = contact.get("aliases") or ""
            if aliases:
                alias_list = [a.strip() for a in aliases.split(";") if a.strip()]
                if alias_list:
                    entry += f" (also known as: {', '.join(alias_list)})"

            lines.append(entry)

            # Add relationship context if present
            rels_json = contact.get("relationships")
            if rels_json:
                try:
                    rels = json.loads(rels_json)
                except (json.JSONDecodeError, TypeError):
                    rels = {}

                context_parts = []

                # Relationship to Stephen Andrews
                rel_to_stephen = rels.get("relation_to_stephen") or rels.get("relationship")
                if rel_to_stephen:
                    context_parts.append(f"Relationship to Stephen Andrews: {rel_to_stephen}")

                # Personal group
                group = rels.get("personal_group")
                if group:
                    context_parts.append(f"Group: {group}")

                # Contact type
                ctype = rels.get("contact_type")
                if ctype:
                    context_parts.append(f"Type: {ctype}")

                # Tags
                tags = rels.get("tags", [])
                if tags:
                    context_parts.append(f"Tags: {', '.join(tags)}")

                # How we met
                how_met = rels.get("how_we_met")
                if how_met:
                    context_parts.append(f"How met: {how_met}")

                if context_parts:
                    lines.append(f"  Context: {'; '.join(context_parts)}")

        # Add disambiguation warning if any first names are shared
        ambiguous_names = {fn: names for fn, names in first_names_seen.items() if len(names) > 1}
        if ambiguous_names:
            lines.append("")
            lines.append("⚠️ NAME DISAMBIGUATION REQUIRED:")
            for first_name, full_names in ambiguous_names.items():
                names_str = " and ".join(f'"{n}"' for n in full_names)
                lines.append(
                    f"  Multiple people named \"{first_name}\": {names_str}. "
                    f"You MUST use full names for ALL references to anyone named \"{first_name}\"."
                )

        lines.append("")
        return "\n".join(lines)

    except Exception as e:
        logger.warning(f"Failed to build participant roster: {e}")
        return ""
    finally:
        conn.close()


# ── Transcript slicing ──────────────────────────────────────────

def _parse_turn_start(line: str) -> float | None:
    """Extract the start timestamp from a transcript line like '[120-135s] Speaker: text'."""
    match = re.match(r"\[(\d+)-\d+s?\]", line)
    return float(match.group(1)) if match else None


def _slice_transcript_by_turns(
    transcript_text: str,
    target_start: float,
    target_end: float,
    buffer_start: float | None,
    buffer_end: float | None,
) -> str:
    """Slice transcript by speaker turn boundaries with buffer.

    Finds the nearest speaker turn at-or-after buffer_start (or target_start
    if no buffer) and the nearest turn at-or-before buffer_end (or target_end).
    Returns transcript lines within that range.

    Args:
        transcript_text: Full transcript with [start-end] timestamps.
        target_start: Start of target episodes (seconds).
        target_end: End of target episodes (seconds).
        buffer_start: Start of buffer episode before target (or None).
        buffer_end: End of buffer episode after target (or None).
    """
    lines = transcript_text.split("\n")
    effective_start = buffer_start if buffer_start is not None else target_start
    effective_end = buffer_end if buffer_end is not None else target_end

    # Find the first speaker turn at-or-after effective_start
    # and the last speaker turn at-or-before effective_end
    result = []
    for line in lines:
        ts = _parse_turn_start(line)
        if ts is not None:
            if ts >= effective_start and ts < effective_end:
                result.append(line)
        # Include non-timestamped lines only if we're within range
        elif result:
            result.append(line)

    return "\n".join(result)


# ── Batch extraction ────────────────────────────────────────────

async def _extract_batch_async(
    client: anthropic.AsyncAnthropic,
    system: str,
    transcript_slice: str,
    batch_episodes: list[Episode],
    batch_offset: int,
    all_episode_summaries: str,
    target_episode_ids: set[str],
    participant_roster: str = "",
) -> tuple[ClaimsResult, dict]:
    """Extract claims from a batch of episodes (async).

    Args:
        client: Async Anthropic client.
        system: System prompt.
        transcript_slice: Transcript covering target + buffer episodes.
        batch_episodes: The target episodes for this batch.
        batch_offset: Index offset for episode numbering (0-based).
        all_episode_summaries: Full list of all episode summaries for context.
        target_episode_ids: Set of episode_ids this batch should extract.
        participant_roster: Formatted roster of identified participants.

    Returns:
        (ClaimsResult with post-filtered claims, usage_dict)
    """
    # Build episode instructions
    ep_nums = []
    for i, ep in enumerate(batch_episodes):
        ep_num = batch_offset + i + 1
        ep_nums.append(ep_num)

    ep_names = ", ".join(f"episode_{n:03d}" for n in ep_nums)
    ep_list = "\n".join(
        f"Episode {batch_offset + i + 1} (episode_{batch_offset + i + 1:03d}): "
        f"[{ep.start_time:.0f}-{ep.end_time:.0f}s] {ep.episode_type} — {ep.title}: {ep.summary}"
        for i, ep in enumerate(batch_episodes)
    )

    # Build user content — roster first, then task, then transcript
    parts = []

    if participant_roster:
        parts.append(participant_roster)

    parts.append(f"## Context: All Episode Summaries\n{all_episode_summaries}")
    parts.append(
        f"## YOUR TASK: Extract claims ONLY from these episodes: {ep_names}\n{ep_list}\n\n"
        f"The transcript below may include surrounding context. "
        f"Extract claims ONLY from the episodes listed above."
    )
    parts.append(f"---\n\n## Transcript\n\n{transcript_slice}")

    user_content = "\n\n".join(parts)

    response = await client.messages.create(
        model=CLAIMS_MODEL,
        max_tokens=16384,
        system=system,
        messages=[{"role": "user", "content": user_content}],
    )

    if response.stop_reason == "max_tokens":
        logger.warning(
            f"Batch (episodes {ep_nums[0]}-{ep_nums[-1]}) "
            f"hit max_tokens ({response.usage.output_tokens} output tokens)."
        )

    raw_text = response.content[0].text.strip()
    json_text = extract_json(raw_text)
    result = ClaimsResult.model_validate_json(json_text)

    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }

    # ── Hard post-filter: drop claims from non-target episodes ──
    pre_filter = len(result.claims)
    result.claims = [
        c for c in result.claims
        if c.episode_id is None or c.episode_id in target_episode_ids
    ]
    dropped = pre_filter - len(result.claims)
    if dropped:
        logger.info(f"    Post-filter: dropped {dropped} claims from context episodes")

    return result, usage


# ── Main entry point ────────────────────────────────────────────

def extract_claims(
    transcript_text: str,
    episodes: list[Episode],
    amendment_context: str = "",
    speaker_map: dict | None = None,
    conversation_id: str = "",
) -> tuple[ClaimsResult, dict]:
    """Run Sonnet claims extraction on a conversation in episode batches.

    Processes episodes in concurrent batches of EPISODES_PER_BATCH.
    Each batch gets a transcript slice with one episode of buffer on
    each side for context, plus a hard post-filter to prevent leakage.

    Args:
        transcript_text: Formatted diarized transcript with speaker names.
        episodes: Episode boundaries from Haiku triage.
        amendment_context: Learned preferences to append to system prompt.
        speaker_map: Dict mapping speaker labels to unified_contacts IDs.

    Returns:
        (ClaimsResult, usage_dict)
    """
    # Run the async implementation in a new event loop
    # (processor.py calls us synchronously)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Already in an async context (e.g., FastAPI background task)
        # Create a new thread to run our event loop
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(
                asyncio.run,
                _extract_claims_async(transcript_text, episodes, amendment_context, speaker_map, conversation_id),
            )
            return future.result()
    else:
        return asyncio.run(
            _extract_claims_async(transcript_text, episodes, amendment_context, speaker_map, conversation_id)
        )


async def _extract_claims_async(
    transcript_text: str,
    episodes: list[Episode],
    amendment_context: str = "",
    speaker_map: dict | None = None,
    conversation_id: str = "",
) -> tuple[ClaimsResult, dict]:
    """Async implementation of claims extraction with concurrent batches."""
    client = anthropic.AsyncAnthropic(timeout=300.0, max_retries=2)

    system = CLAIMS_SYSTEM_PROMPT
    if amendment_context:
        system += f"\n\n{amendment_context}"

    # Build participant roster from speaker_map
    participant_roster = _build_participant_roster(speaker_map)
    if participant_roster:
        logger.info(f"Built participant roster with {len(speaker_map)} speakers")

    # If no episodes, process the whole transcript as one call
    if not episodes:
        logger.info("No episodes — extracting claims from full transcript...")
        result, usage = await _extract_batch_async(
            client, system, transcript_text, [], 0, "", set(),
            participant_roster=participant_roster,
        )
        return result, usage

    # C4: Skip batching for ≤3 episodes — single call is simpler + cheaper
    if len(episodes) <= EPISODES_PER_BATCH:
        logger.info(f"≤{EPISODES_PER_BATCH} episodes — single-call extraction (no batching)")
        all_episode_summaries = "\n".join(
            f"Episode {i+1} (episode_{i+1:03d}): [{ep.start_time:.0f}-{ep.end_time:.0f}s] "
            f"{ep.episode_type} — {ep.title}: {ep.summary}"
            for i, ep in enumerate(episodes)
        )
        all_ids = {f"episode_{i+1:03d}" for i in range(len(episodes))}
        result, usage = await _extract_batch_async(
            client, system, transcript_text, episodes, 0,
            all_episode_summaries, all_ids,
            participant_roster=participant_roster,
        )
        return result, usage

    # Build all-episode summaries for context in each batch
    all_episode_summaries = "\n".join(
        f"Episode {i+1} (episode_{i+1:03d}): [{ep.start_time:.0f}-{ep.end_time:.0f}s] "
        f"{ep.episode_type} — {ep.title}: {ep.summary}"
        for i, ep in enumerate(episodes)
    )

    # Build batches with buffer info
    batches = []
    for i in range(0, len(episodes), EPISODES_PER_BATCH):
        target_eps = episodes[i:i + EPISODES_PER_BATCH]
        offset = i

        # Target time range
        target_start = min(ep.start_time for ep in target_eps)
        target_end = max(ep.end_time for ep in target_eps)

        # Buffer: one episode before and after
        buffer_start = episodes[i - 1].start_time if i > 0 else None
        buffer_end = episodes[min(i + EPISODES_PER_BATCH, len(episodes) - 1)].end_time \
            if i + EPISODES_PER_BATCH < len(episodes) else None

        # Target episode IDs for post-filter
        target_ids = {f"episode_{offset + j + 1:03d}" for j in range(len(target_eps))}

        # Slice transcript by speaker turn boundaries with buffer
        transcript_slice = _slice_transcript_by_turns(
            transcript_text, target_start, target_end, buffer_start, buffer_end
        )

        batches.append({
            "target_eps": target_eps,
            "offset": offset,
            "target_ids": target_ids,
            "transcript_slice": transcript_slice,
            "target_start": target_start,
            "target_end": target_end,
        })

    logger.info(
        f"Running Sonnet claims extraction: {len(episodes)} episodes "
        f"in {len(batches)} batches of ≤{EPISODES_PER_BATCH} "
        f"(max {MAX_CONCURRENCY} concurrent)..."
    )

    # Process batches concurrently with semaphore for rate limiting
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    total_usage = {"input_tokens": 0, "output_tokens": 0}

    async def run_batch(batch_idx: int, batch: dict) -> tuple[int, ClaimsResult | None, dict]:
        """Run a single batch with retry."""
        async with semaphore:
            offset = batch["offset"]
            target_eps = batch["target_eps"]
            ep_range = f"{offset+1}-{offset+len(target_eps)}"

            logger.info(
                f"  Batch {batch_idx+1}/{len(batches)}: episodes {ep_range}, "
                f"[{batch['target_start']:.0f}-{batch['target_end']:.0f}s], "
                f"{len(batch['transcript_slice'].splitlines())} lines"
            )

            # Try up to 2 times (initial + 1 retry)
            for attempt in range(2):
                try:
                    result, usage = await _extract_batch_async(
                        client, system,
                        batch["transcript_slice"],
                        target_eps, offset,
                        all_episode_summaries,
                        batch["target_ids"],
                        participant_roster=participant_roster,
                    )
                    logger.info(
                        f"    → {len(result.claims)} claims, "
                        f"{usage['input_tokens']} in / {usage['output_tokens']} out"
                    )
                    return batch_idx, result, usage

                except Exception as e:
                    if attempt == 0:
                        logger.warning(
                            f"  Batch {batch_idx+1} failed ({type(e).__name__}: {e}), retrying..."
                        )
                    else:
                        logger.error(
                            f"  Batch {batch_idx+1} failed on retry ({type(e).__name__}: {e}). "
                            f"Skipping episodes {ep_range}."
                        )

            return batch_idx, None, {"input_tokens": 0, "output_tokens": 0}

    # Launch all batches concurrently
    tasks = [run_batch(i, b) for i, b in enumerate(batches)]
    results = await asyncio.gather(*tasks)

    # Merge results in batch order
    all_claims = []
    all_memory_writes = []
    all_people_mentioned = set()
    all_new_contacts_map = {}
    _seen_claim_hashes = set()

    for batch_idx, result, usage in sorted(results, key=lambda r: r[0]):
        total_usage["input_tokens"] += usage["input_tokens"]
        total_usage["output_tokens"] += usage["output_tokens"]

        if result is None:
            continue

        for claim in result.claims:
            # Step G: Content-deterministic claim IDs.
            #
            # Hash basis includes all semantically identifying fields:
            #   - conversation_id: scopes ID to conversation
            #   - claim_type: fact|position|commitment|preference|...
            #   - claim_text: normalized (lowered, stripped)
            #   - subject_name: who the claim is about
            #   - target_entity: second entity if relational
            #   - speaker: who said it
            #
            # Same semantic claim → same ID regardless of extraction
            # order or batch assignment. Different conversations with
            # identical claim text → different IDs (conversation-scoped).
            _claim_text_norm = (
                getattr(claim, "claim_text", "") or ""
            ).strip().lower()
            _hash_input = "|".join([
                conversation_id,
                getattr(claim, "claim_type", "") or "",
                _claim_text_norm,
                getattr(claim, "subject_name", "") or "",
                getattr(claim, "target_entity", "") or "",
                getattr(claim, "speaker", "") or "",
            ])
            _hash_hex = hashlib.sha256(
                _hash_input.encode("utf-8")
            ).hexdigest()[:12]
            # 12 hex chars = 48 bits ≈ 281 trillion possibilities
            # Handle collisions within conversation (extremely rare)
            _candidate = f"claim_{_hash_hex}"
            _suffix = 0
            while _candidate in _seen_claim_hashes:
                _suffix += 1
                _candidate = f"claim_{_hash_hex}_{_suffix}"
            _seen_claim_hashes.add(_candidate)
            claim.id = _candidate
            all_claims.append(claim)

        all_memory_writes.extend(result.memory_writes)
        all_people_mentioned.update(p.strip() for p in result.people_mentioned if p.strip())
        for mention in result.new_contacts_mentioned:
            if isinstance(mention, str):
                name = mention.strip()
                if name and name not in all_new_contacts_map:
                    all_new_contacts_map[name] = mention
            else:
                name = (getattr(mention, 'name', '') or '').strip()
                if name:
                    all_new_contacts_map[name] = mention  # structured overrides string

    # Merge into single result
    merged = ClaimsResult(
        claims=all_claims,
        memory_writes=all_memory_writes,
        people_mentioned=sorted(all_people_mentioned),
        new_contacts_mentioned=list(all_new_contacts_map.values()),
    )

    # Instrumentation
    type_counts = {}
    modality_counts = {}
    confidence_brackets = {"0-0.3": 0, "0.3-0.6": 0, "0.6-0.8": 0, "0.8-1.0": 0}
    for c in merged.claims:
        type_counts[c.claim_type] = type_counts.get(c.claim_type, 0) + 1
        modality_counts[c.modality] = modality_counts.get(c.modality, 0) + 1
        if c.confidence < 0.3:
            confidence_brackets["0-0.3"] += 1
        elif c.confidence < 0.6:
            confidence_brackets["0.3-0.6"] += 1
        elif c.confidence < 0.8:
            confidence_brackets["0.6-0.8"] += 1
        else:
            confidence_brackets["0.8-1.0"] += 1

    logger.info(
        f"Claims extraction complete: {len(merged.claims)} claims across {len(batches)} batches | "
        f"types={type_counts} | modality={modality_counts} | "
        f"confidence={confidence_brackets} | "
        f"{len(merged.memory_writes)} memory writes, "
        f"{len(merged.new_contacts_mentioned)} new contacts | "
        f"total tokens: {total_usage['input_tokens']} in / {total_usage['output_tokens']} out"
    )

    return merged, total_usage
