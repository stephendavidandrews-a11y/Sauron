"""Gate test for Step 4: Text Extraction.

Tests:
1. Format a cluster for extraction (preprocessor)
2. Run Haiku triage on cluster (assigns depth lane)
3. Run Sonnet claims extraction on Lane 2+ clusters
4. Inspect claim quality manually
5. Check evidence_quality assignment

THIS TEST HITS THE CLAUDE API (~$0.03 per cluster)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import json
from dotenv import load_dotenv
load_dotenv()

from sauron.text.identity import build_phone_index
from sauron.text.preprocessor import format_cluster_for_extraction, build_text_participant_roster
from sauron.text.text_extraction import triage_text_cluster, extract_text_claims
from sauron.config import DB_PATH

import sqlite3


def main():
    print("=" * 60)
    print("GATE TEST: Text Extraction (Step 4)")
    print("=" * 60)

    # Build phone index
    phone_index = build_phone_index()
    print(f"\n[1] Phone index: {len(phone_index)} contacts")

    # Get clusters from DB
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    clusters = conn.execute(
        """SELECT tc.id, tc.thread_id, tc.message_count, tc.participant_count,
                  tc.depth_lane, tc.start_time, tc.end_time,
                  tt.thread_type, tt.display_name
           FROM text_clusters tc
           JOIN text_threads tt ON tc.thread_id = tt.id
           ORDER BY tc.message_count DESC"""
    ).fetchall()

    print(f"\n[2] Found {len(clusters)} clusters in DB")

    if not clusters:
        print("[WARN] No clusters found! Run Step 3 gate test first.")
        conn.close()
        return

    # Pick up to 3 clusters for testing (largest first)
    test_clusters = clusters[:3]
    print(f"    Testing {len(test_clusters)} clusters")

    total_triage_cost = 0
    total_extract_cost = 0

    for i, cluster in enumerate(test_clusters):
        print(f"\n{'─' * 50}")
        print(f"CLUSTER {i+1}: {cluster['display_name']} ({cluster['thread_type']})")
        print(f"  Messages: {cluster['message_count']}, Participants: {cluster['participant_count']}")
        print(f"  Time: {cluster['start_time'][:16]} → {cluster['end_time'][:16]}")
        print(f"{'─' * 50}")

        # Step 1: Format for extraction
        formatted = format_cluster_for_extraction(
            cluster["id"], phone_index=phone_index
        )

        print(f"\n  [Preprocessor] {formatted['line_count']} lines, {formatted['total_chars']} chars")
        print(f"  Participants: {', '.join(formatted['participant_names'])}")

        # Show first 10 lines of transcript
        lines = formatted["transcript"].split("\n")
        print(f"\n  --- Transcript preview (first 10 lines) ---")
        for line in lines[:10]:
            print(f"    {line}")
        if len(lines) > 10:
            print(f"    ... ({len(lines) - 10} more lines)")

        # Step 2: Build participant roster
        roster = build_text_participant_roster(formatted["participant_map"])
        if roster:
            print(f"\n  --- Participant Roster ---")
            for line in roster.split("\n")[:8]:
                print(f"    {line}")

        # Step 3: Run triage
        print(f"\n  [Triage] Running Haiku triage...")
        triage, triage_usage = triage_text_cluster(
            formatted["transcript"], formatted["metadata"]
        )

        print(f"    Lane: {triage.get('depth_lane', '?')}")
        print(f"    Classification: {triage.get('cluster_classification', '?')}")
        print(f"    Value: {triage.get('value_assessment', '?')}")
        print(f"    Summary: {triage.get('summary', '?')}")
        print(f"    Topics: {triage.get('topic_tags', [])}")
        print(f"    Actionable: {triage.get('has_actionable_content', '?')}")
        print(f"    Rationale: {triage.get('depth_rationale', '?')}")

        triage_tokens = getattr(triage_usage, "input_tokens", 0) + getattr(triage_usage, "output_tokens", 0)
        # Rough cost: Haiku ~$0.25/1M input, $1.25/1M output
        triage_cost = (
            getattr(triage_usage, "input_tokens", 0) * 0.25 / 1_000_000 +
            getattr(triage_usage, "output_tokens", 0) * 1.25 / 1_000_000
        )
        total_triage_cost += triage_cost
        print(f"    Cost: ~${triage_cost:.4f}")

        # Step 4: Extract claims (only for Lane 2+)
        depth_lane = triage.get("depth_lane", 0)
        if depth_lane >= 2:
            print(f"\n  [Extract] Running Sonnet claims extraction (Lane {depth_lane})...")

            claims_result, extract_usage = extract_text_claims(
                formatted["transcript"],
                roster,
                formatted["metadata"],
                triage,
                conversation_id=f"text_{cluster['id']}",
            )

            # Rough cost: Sonnet ~$3/1M input, $15/1M output
            extract_cost = (
                extract_usage["input_tokens"] * 3.0 / 1_000_000 +
                extract_usage["output_tokens"] * 15.0 / 1_000_000
            )
            total_extract_cost += extract_cost
            print(f"    Cost: ~${extract_cost:.4f}")
            print(f"    Tokens: {extract_usage['input_tokens']} in / {extract_usage['output_tokens']} out")

            print(f"\n  [Claims] {len(claims_result.claims)} claims extracted:")
            for j, claim in enumerate(claims_result.claims):
                eq = getattr(claim, "evidence_quality", "?") or "?"
                print(f"\n    Claim {j+1}: [{claim.claim_type}] (conf={claim.confidence}, eq={eq})")
                print(f"      Text: {claim.claim_text}")
                print(f"      Subject: {claim.subject_name}")
                print(f"      Speaker: {claim.speaker}")
                print(f"      Evidence: {(claim.evidence_quote or '')[:80]}")
                if claim.claim_type == "commitment":
                    print(f"      Firmness: {claim.firmness}, Direction: {claim.direction}")

            if claims_result.memory_writes:
                print(f"\n  [Memory] {len(claims_result.memory_writes)} memory writes:")
                for mw in claims_result.memory_writes:
                    print(f"    {mw.entity_name}.{mw.field} = {mw.value}")

            if claims_result.new_contacts_mentioned:
                print(f"\n  [New contacts] {len(claims_result.new_contacts_mentioned)}:")
                for nc in claims_result.new_contacts_mentioned:
                    if isinstance(nc, str):
                        print(f"    {nc}")
                    else:
                        print(f"    {nc.name} (context: {nc.context})")

        else:
            print(f"\n  [Skip] Lane {depth_lane} — no claims extraction needed")
            if depth_lane == 0:
                print(f"    Stored as thin capture (Lane 0)")
            elif depth_lane == 1:
                print(f"    Stored as Haiku label (Lane 1) — available for search")

    # Cost summary
    print(f"\n{'=' * 60}")
    print(f"COST SUMMARY")
    print(f"  Triage (Haiku): ${total_triage_cost:.4f}")
    print(f"  Extraction (Sonnet): ${total_extract_cost:.4f}")
    print(f"  Total: ${total_triage_cost + total_extract_cost:.4f}")
    print(f"{'=' * 60}")

    conn.close()
    print(f"\n[DONE] Extraction gate test complete.")


if __name__ == "__main__":
    main()
