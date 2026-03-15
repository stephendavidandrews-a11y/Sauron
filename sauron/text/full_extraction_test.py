"""Comprehensive Step 4 extraction test - forces Sonnet on ALL clusters.

Tests extraction quality across diverse cluster types:
- Group work threads (legislative strategy)
- 1:1 conversations
- Logistical/abbreviated exchanges
- Personal/social threads

Runs Haiku triage on all clusters, then forces Sonnet extraction on ALL
regardless of triage lane - so we can inspect claim quality for low-substance
clusters too.

THIS TEST HITS THE CLAUDE API (~$0.09-0.15 total)
"""
import sys, os
from pathlib import Path

# Ensure project root on path and .env loaded
project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
env_file = project_root / ".env"
if env_file.exists():
    load_dotenv(env_file)

assert os.environ.get("ANTHROPIC_API_KEY"), "ANTHROPIC_API_KEY not set - check .env file"

import json, sqlite3
from sauron.text.identity import build_phone_index
from sauron.text.preprocessor import format_cluster_for_extraction, build_text_participant_roster
from sauron.text.text_extraction import triage_text_cluster, extract_text_claims
from sauron.config import DB_PATH


def main():
    print("=" * 70)
    print("COMPREHENSIVE EXTRACTION TEST - ALL CLUSTERS, FORCED SONNET")
    print("=" * 70)

    phone_index = build_phone_index()
    print(f"\nPhone index: {len(phone_index)} contacts")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    clusters = conn.execute("""
        SELECT tc.id, tc.thread_id, tc.message_count, tc.participant_count,
               tc.start_time, tc.end_time,
               tt.thread_type, tt.display_name, tt.participant_phones
        FROM text_clusters tc
        JOIN text_threads tt ON tc.thread_id = tt.id
        ORDER BY tc.start_time
    """).fetchall()

    print(f"Found {len(clusters)} clusters\n")

    all_results = []
    total_cost = 0.0

    for i, cluster in enumerate(clusters):
        cid = cluster["id"]
        name = cluster["display_name"] or "(1:1 thread)"
        ctype = cluster["thread_type"]
        mc = cluster["message_count"]

        print(f"\n{'=' * 70}")
        print(f"CLUSTER {i+1}/{len(clusters)}: {name} ({ctype}, {mc} msgs)")
        print(f"  Time: {cluster['start_time'][:19]} -> {cluster['end_time'][:19]}")
        print(f"{'=' * 70}")

        # Format
        formatted = format_cluster_for_extraction(cid, phone_index=phone_index)
        print(f"\n  Transcript: {formatted['line_count']} lines, {formatted['total_chars']} chars")
        print(f"  Participants: {', '.join(formatted['participant_names'])}")

        # Full transcript
        print(f"\n  --- FULL TRANSCRIPT ---")
        for line in formatted["transcript"].split("\n"):
            print(f"  | {line}")
        print(f"  --- END TRANSCRIPT ---")

        # Roster
        roster = build_text_participant_roster(formatted["participant_map"])

        # Triage
        print(f"\n  [Triage] Running Haiku...")
        triage, triage_usage = triage_text_cluster(
            formatted["transcript"], formatted["metadata"]
        )

        lane = triage.get("depth_lane", 0)
        classification = triage.get("cluster_classification", "?")
        value = triage.get("value_assessment", "?")
        summary = triage.get("summary", "?")
        topics = triage.get("topic_tags", [])
        actionable = triage.get("has_actionable_content", "?")
        rationale = triage.get("depth_rationale", "?")

        triage_cost = (
            getattr(triage_usage, "input_tokens", 0) * 0.25 / 1_000_000 +
            getattr(triage_usage, "output_tokens", 0) * 1.25 / 1_000_000
        )

        print(f"    Lane: {lane} | Classification: {classification} | Value: {value}")
        print(f"    Summary: {summary}")
        print(f"    Topics: {topics}")
        print(f"    Actionable: {actionable}")
        print(f"    Rationale: {rationale}")

        # FORCE Sonnet extraction on ALL clusters (even Lane 0/1)
        force_note = ""
        if lane < 2:
            force_note = f" [FORCED - triage assigned Lane {lane}]"
            print(f"\n  [Extract] FORCING Sonnet extraction (triage said Lane {lane}){force_note}")
        else:
            print(f"\n  [Extract] Running Sonnet extraction (Lane {lane})")

        claims_result, extract_usage = extract_text_claims(
            formatted["transcript"],
            roster,
            formatted["metadata"],
            triage,
            conversation_id=f"test_{cid[:8]}",
        )

        extract_cost = (
            extract_usage["input_tokens"] * 3.0 / 1_000_000 +
            extract_usage["output_tokens"] * 15.0 / 1_000_000
        )

        cluster_cost = triage_cost + extract_cost
        total_cost += cluster_cost

        print(f"    Tokens: {extract_usage['input_tokens']} in / {extract_usage['output_tokens']} out")
        print(f"    Cluster cost: ${cluster_cost:.4f}")

        # Claims output
        claims = claims_result.claims
        memory_writes = claims_result.memory_writes or []
        new_contacts = claims_result.new_contacts_mentioned or []

        print(f"\n  --- CLAIMS ({len(claims)}) ---")
        if not claims:
            print(f"  |  (zero claims - expected for thin/logistical clusters)")

        result_entry = {
            "cluster_id": cid,
            "name": name,
            "type": ctype,
            "messages": mc,
            "triage_lane": lane,
            "classification": classification,
            "value": value,
            "force_note": force_note,
            "claim_count": len(claims),
            "claims": [],
            "memory_writes": len(memory_writes),
            "new_contacts": len(new_contacts),
        }

        for j, claim in enumerate(claims):
            eq = getattr(claim, "evidence_quality", None) or "not_set"
            print(f"  |")
            print(f"  |  Claim {j+1}: [{claim.claim_type}] conf={claim.confidence} eq={eq}")
            print(f"  |    Text: {claim.claim_text}")
            print(f"  |    Subject: {claim.subject_name}")
            print(f"  |    Speaker: {claim.speaker}")
            if claim.evidence_quote:
                eq_text = claim.evidence_quote[:100]
                print(f"  |    Evidence: {eq_text}")
            if claim.claim_type == "commitment":
                print(f"  |    Firmness: {claim.firmness}, Direction: {claim.direction}")
            if claim.claim_type == "relationship":
                print(f"  |    Target: {claim.target_entity}")

            result_entry["claims"].append({
                "type": claim.claim_type,
                "text": claim.claim_text,
                "subject": claim.subject_name,
                "speaker": claim.speaker,
                "confidence": claim.confidence,
                "evidence_quality": eq,
                "evidence": (claim.evidence_quote or "")[:150],
                "firmness": getattr(claim, "firmness", None),
                "direction": getattr(claim, "direction", None),
                "target_entity": getattr(claim, "target_entity", None),
            })

        print(f"  --- END CLAIMS ---")

        if memory_writes:
            print(f"\n  Memory writes ({len(memory_writes)}):")
            for mw in memory_writes:
                print(f"    {mw.entity_name}.{mw.field} = {mw.value}")

        if new_contacts:
            print(f"\n  New contacts flagged ({len(new_contacts)}):")
            for nc in new_contacts:
                if isinstance(nc, str):
                    print(f"    {nc}")
                else:
                    print(f"    {nc.name} - {nc.context}")

        all_results.append(result_entry)

    # SUMMARY
    print(f"\n\n{'=' * 70}")
    print(f"EXTRACTION QUALITY SUMMARY")
    print(f"{'=' * 70}")
    print(f"\nTotal clusters: {len(all_results)}")
    print(f"Total cost: ${total_cost:.4f}")

    total_claims = sum(r["claim_count"] for r in all_results)
    print(f"Total claims: {total_claims}")

    # Per-cluster summary
    print(f"\n{'_' * 70}")
    print(f"{'Cluster':<30} {'Type':<6} {'Msgs':>4} {'Lane':>4} {'Claims':>6} {'Note'}")
    print(f"{'_' * 70}")
    for r in all_results:
        print(f"{r['name'][:30]:<30} {r['type']:<6} {r['messages']:>4} {r['triage_lane']:>4} {r['claim_count']:>6} {r['force_note']}")

    # Claim type distribution
    type_counts = {}
    eq_counts = {}
    for r in all_results:
        for c in r["claims"]:
            type_counts[c["type"]] = type_counts.get(c["type"], 0) + 1
            eq_counts[c["evidence_quality"]] = eq_counts.get(c["evidence_quality"], 0) + 1

    print(f"\nClaim type distribution:")
    for t, n in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {t}: {n}")

    print(f"\nEvidence quality distribution:")
    for eq, n in sorted(eq_counts.items(), key=lambda x: -x[1]):
        print(f"  {eq}: {n}")

    # Write raw results to JSON for post-inspection
    output_path = Path(__file__).parent / "extraction_results.json"
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nRaw results written to: {output_path}")

    conn.close()
    print(f"\n[DONE]")


if __name__ == "__main__":
    main()
