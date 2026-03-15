"""Comprehensive Step 4 extraction test v2 — with all prompt fixes.

Forces Sonnet extraction on ALL clusters regardless of triage lane.
Outputs full claim details for quality comparison against v1 run.

THIS TEST HITS THE CLAUDE API (~$0.12-0.18 total)
"""
import sys, os, json, sqlite3
from pathlib import Path

# Ensure project root on path and .env loaded
project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
env_file = project_root / ".env"
if env_file.exists():
    load_dotenv(env_file)

assert os.environ.get("ANTHROPIC_API_KEY"), "ANTHROPIC_API_KEY not set"

from sauron.text.identity import build_phone_index
from sauron.text.preprocessor import format_cluster_for_extraction, build_text_participant_roster
from sauron.text.text_extraction import triage_text_cluster, extract_text_claims
from sauron.config import DB_PATH


def main():
    print("=" * 70)
    print("EXTRACTION TEST v2 — ALL PROMPT FIXES APPLIED")
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
        cid = cluster['id']
        name = cluster['display_name'] or '(1:1 thread)'
        ctype = cluster['thread_type']
        mc = cluster['message_count']

        print(f"\n{'═' * 70}")
        print(f"CLUSTER {i+1}/{len(clusters)}: {name} ({ctype}, {mc} msgs)")
        print(f"  Time: {cluster['start_time'][:19]} → {cluster['end_time'][:19]}")
        print(f"{'═' * 70}")

        # Format
        formatted = format_cluster_for_extraction(cid, phone_index=phone_index)
        print(f"\n  Transcript: {formatted['line_count']} lines, {formatted['total_chars']} chars")
        print(f"  Participants: {', '.join(formatted['participant_names'])}")

        # Full transcript
        print(f"\n  ┌── FULL TRANSCRIPT ──")
        for line in formatted["transcript"].split("\n"):
            print(f"  │ {line}")
        print(f"  └── END TRANSCRIPT ──")

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

        triage_cost = (
            getattr(triage_usage, "input_tokens", 0) * 0.25 / 1_000_000 +
            getattr(triage_usage, "output_tokens", 0) * 1.25 / 1_000_000
        )

        print(f"    Lane: {lane} | Class: {classification} | Value: {value}")
        print(f"    Summary: {summary}")

        # FORCE Sonnet extraction on ALL clusters
        force_note = ""
        if lane < 2:
            force_note = f" [FORCED from Lane {lane}]"
            print(f"\n  [Extract] FORCING Sonnet (triage said Lane {lane})")
        else:
            print(f"\n  [Extract] Running Sonnet (Lane {lane})")

        claims_result, extract_usage = extract_text_claims(
            formatted["transcript"],
            roster,
            formatted["metadata"],
            triage,
            conversation_id=f"test_v2_{cid[:8]}",
        )

        extract_cost = (
            extract_usage["input_tokens"] * 3.0 / 1_000_000 +
            extract_usage["output_tokens"] * 15.0 / 1_000_000
        )

        cluster_cost = triage_cost + extract_cost
        total_cost += cluster_cost

        claims = claims_result.claims
        memory_writes = claims_result.memory_writes or []
        new_contacts = claims_result.new_contacts_mentioned or []

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
            "memory_writes": [],
            "new_contacts": [],
        }

        print(f"\n  ┌── CLAIMS ({len(claims)}) ──")
        if not claims:
            print(f"  │  (zero claims)")

        for j, claim in enumerate(claims):
            eq = getattr(claim, "evidence_quality", None) or "not_set"
            dd = getattr(claim, "due_date", None)
            dc = getattr(claim, "date_confidence", None)
            dn = getattr(claim, "date_note", None)
            ct = getattr(claim, "condition_trigger", None)
            rec = getattr(claim, "recurrence", None)
            rc = getattr(claim, "related_claim_id", None)

            print(f"  │")
            print(f"  │  Claim {j+1}: [{claim.claim_type}] conf={claim.confidence} eq={eq}")
            print(f"  │    Text: {claim.claim_text}")
            print(f"  │    Subject: {claim.subject_name} | Speaker: {claim.speaker}")
            if claim.evidence_quote:
                print(f"  │    Evidence: {claim.evidence_quote[:100]}")
            if claim.claim_type == "commitment":
                print(f"  │    Firmness: {claim.firmness} | Direction: {claim.direction}")
                if dd:
                    print(f"  │    Due date: {dd} ({dc})")
                if dn:
                    print(f"  │    Date note: {dn}")
                if ct:
                    print(f"  │    Condition trigger: {ct}")
                if rec:
                    print(f"  │    Recurrence: {rec}")
            if rc:
                print(f"  │    Related claim: {rc}")

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
                "due_date": dd,
                "date_confidence": dc,
                "date_note": dn,
                "condition_trigger": ct,
                "recurrence": rec,
                "related_claim_id": rc,
            })

        print(f"  └── END CLAIMS ──")

        if memory_writes:
            print(f"\n  Memory writes ({len(memory_writes)}):")
            for mw in memory_writes:
                print(f"    {mw.entity_name}.{mw.field} = {mw.value}")
                result_entry["memory_writes"].append({
                    "entity": mw.entity_name,
                    "field": mw.field,
                    "value": mw.value,
                })

        if new_contacts:
            print(f"\n  New contacts ({len(new_contacts)}):")
            for nc in new_contacts:
                if isinstance(nc, str):
                    print(f"    {nc}")
                    result_entry["new_contacts"].append({"name": nc})
                else:
                    org = getattr(nc, "organization", None) or ""
                    ctx = getattr(nc, "context", None) or ""
                    print(f"    {nc.name} — {org} — {ctx}")
                    result_entry["new_contacts"].append({
                        "name": nc.name,
                        "organization": org,
                        "context": ctx,
                    })

        all_results.append(result_entry)

    # ═══════════════════════════════════════════════
    # SUMMARY
    # ═══════════════════════════════════════════════
    print(f"\n\n{'═' * 70}")
    print(f"EXTRACTION QUALITY SUMMARY (v2)")
    print(f"{'═' * 70}")
    print(f"\nTotal clusters: {len(all_results)}")
    print(f"Total cost: ${total_cost:.4f}")

    total_claims = sum(r["claim_count"] for r in all_results)
    print(f"Total claims: {total_claims}")

    print(f"\n{'─' * 70}")
    print(f"{'Cluster':<30} {'Type':<6} {'Msgs':>4} {'Lane':>4} {'Claims':>6} {'Note'}")
    print(f"{'─' * 70}")
    for r in all_results:
        print(f"{r['name'][:30]:<30} {r['type']:<6} {r['messages']:>4} {r['triage_lane']:>4} {r['claim_count']:>6} {r['force_note']}")

    # Claim type distribution
    type_counts = {}
    eq_counts = {}
    firmness_counts = {}
    date_counts = {"has_due_date": 0, "no_due_date": 0}
    for r in all_results:
        for c in r["claims"]:
            type_counts[c["type"]] = type_counts.get(c["type"], 0) + 1
            eq_counts[c["evidence_quality"]] = eq_counts.get(c["evidence_quality"], 0) + 1
            if c.get("firmness"):
                firmness_counts[c["firmness"]] = firmness_counts.get(c["firmness"], 0) + 1
            if c.get("due_date"):
                date_counts["has_due_date"] += 1
            elif c["type"] == "commitment":
                date_counts["no_due_date"] += 1

    print(f"\nClaim type distribution:")
    for t, n in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {t}: {n}")

    print(f"\nEvidence quality distribution:")
    for eq, n in sorted(eq_counts.items(), key=lambda x: -x[1]):
        print(f"  {eq}: {n}")

    print(f"\nCommitment firmness distribution:")
    for f, n in sorted(firmness_counts.items(), key=lambda x: -x[1]):
        print(f"  {f}: {n}")

    print(f"\nCommitment dates:")
    for k, v in date_counts.items():
        print(f"  {k}: {v}")

    # Write raw results
    output_path = Path(__file__).parent / "extraction_results_v2.json"
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nRaw results: {output_path}")

    conn.close()
    print(f"\n[DONE]")


if __name__ == "__main__":
    main()
