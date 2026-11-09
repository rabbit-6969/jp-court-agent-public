"""
Surgical update to existing ES documents to add graph edges.
1. Verifies 'Residence' string in the Insurer Estimate (DOC-12F199F8).
2. Ingests Agent-Generated reasoning documents (Timeline & Exhibit C Summary).
3. Establishes 'contradicts' and 'supports' edges to build legal reasoning chains.
"""

from es_client_utils import JPCourtESClient
from elasticsearch import helpers
from datetime import datetime
import re

def apply_updates(case_id: str):
    client = JPCourtESClient()

    # Requirement 6.4 Validation
    try:
        client.validate_case_id(case_id)
    except ValueError as e:
        print(f"âŒ Validation Error: {e}")
        return

    # Target IDs from current case state
    ESTIMATE_ID = "DOC-12F199F8"
    PETITION_ID = "DOC-6924EB3F"
    CHECK_ID = "DOC-5C6E8A35"
    MOTION_ID = "DOC-8FC2AF6D"
    ANSWER_ID = "DOC-434A98B5"
    GERBER_ID = "DOC-319415B7"
    CRASH_ID  = "DOC-29FCFE93"

    now_iso = datetime.now().isoformat() + "+00:00"

    def safe_merge_edges(source_id: str, new_edges: list):
        """Helper to perform partial updates with edge merging and target verification."""
        print(f"Surgically updating edges for {source_id}...")
        try:
            # 1. Verify Source exists
            resp = client.es.get(index=client.index_name, id=source_id)
            doc = resp["_source"]
            
            # 2. Filter out edges to non-existent targets
            verified_edges = []
            for edge in new_edges:
                if client.es.exists(index=client.index_name, id=edge["target"]):
                    verified_edges.append(edge)
                else:
                    print(f"  âš ï¸ Skipping dangling edge to {edge['target']} (not in index)")

            # 3. Merge with existing
            existing = doc.get("edges", [])
            seen = {(e["target"], e["relation"]) for e in existing}
            for ne in verified_edges:
                if (ne["target"], ne["relation"]) not in seen:
                    existing.append(ne)

            # 4. Partial Update (Preserves text and embeddings per Requirement 2.6)
            client.es.update(
                index=client.index_name,
                id=source_id,
                body={"doc": {"edges": existing}}
            )
            print(f"  âœ… {source_id} updated.")
        except Exception as e:
            print(f"  âŒ Update failed for {source_id}: {e}")

    # 1. Verify and Update Insurer's Estimate (A)
    print(f"Verifying content for {ESTIMATE_ID}...")
    try:
        est_resp = client.es.get(index=client.index_name, id=ESTIMATE_ID)
        doc = est_resp["_source"]
        
        # Flexible verification for the inspection location string (handles quote variations and spacing)
        target_pattern = r"INSPECTION LOCATION:\s*OWNER['â€™]S\s*RESIDENCE"
        if re.search(target_pattern, doc["text"].upper()):
            print(f"âœ… Verified: Inspection location string found.")
            safe_merge_edges(ESTIMATE_ID, [
                {"target": PETITION_ID, "relation": "is_related_to"},
                {"target": CHECK_ID, "relation": "is_related_to"}
            ])
        else:
            print(f"âŒ Warning: String '{target_string}' NOT found in doc text.")
    except Exception as e:
        print(f"âŒ Error accessing {ESTIMATE_ID}: {e}")

    # 2. Update Procedural Timeline (B)
    print(f"Refining procedural timeline: {MOTION_ID} -> {ANSWER_ID}...")
    safe_merge_edges(MOTION_ID, [
        {"target": ANSWER_ID, "relation": "timeline_precedes"},
        {"target": ANSWER_ID, "relation": "contradicts"}
    ])

    # 3. Ingest Master Timeline Analysis
    print("Ingesting Master Timeline Analysis (AGENT-GENERATED)...")
    timeline_text = """â­ MASTER CASE TIMELINE ANALYSIS
    - 2026-03-08: Collision at 4400 Frankford Road. Defendant rear-ended Plaintiff.
    - 2026-03-22: Crash report issued identifying 'Followed Too Closely' as the primary factor.
    - 2026-05-01: Plaintiff filed Original Petition.
    - 2026-05-07: Defendant personally served with citation.
    - 2026-05-11: Insurer issued partial payment check (#00183869) for $701.64.
    - 2026-06-01: Defendant filed Original Answer 11 days past the legal deadline.
    CONCLUSION: Liability is established via negligence per se. The partial payment constitutes an admission of the underlying claim."""
    
    try:
        client.ingest_document(
            doc_id="AGENT-TIMELINE-ANALYSIS",
            case_id=case_id,
            doc_type="agent_generated",
            title="Master Legal Timeline and Qualifications",
            text=timeline_text,
            date=now_iso,
            tags=["analysis", "graph_chain", "timeline", "legal_qualifications"],
            edges=[
                {"target": PETITION_ID, "relation": "supports"},
                {"target": CRASH_ID, "relation": "is_related_to"},
                {"target": CHECK_ID, "relation": "is_related_to"}
            ]
        )
        print("âœ… Ingested AGENT-TIMELINE-ANALYSIS")
    except ValueError as e:
        print(f"â„¹ï¸ Skipping AGENT-TIMELINE-ANALYSIS: {e}")

    # 4. Ingest Exhibit C Summary
    print("Ingesting Exhibit C Summary (AGENT-GENERATED)...")
    exhibit_c_text = """EXHIBIT C â€” ANALYSIS OF MISREPRESENTED INSPECTION
    The Insurer Estimate (DOC-12F199F8) claims an in-person inspection occurred at the 'Ownerâ€™s Residence' at 4:30 PM.
    However, the Gerber Collision estimate (DOC-319415B7) and Plaintiff's own testimony indicate the vehicle was at the repair facility during this window.
    This discrepancy suggests the $701.64 estimate was generated without a physical inspection of the actual damage, leading to the substantial 
    valuation gap compared to the professional $2,241.43 repair quote. The insurer's reliance on this 'phantom' inspection is a central point of the dispute."""
    
    try:
        client.ingest_document(
            doc_id="AGENT-EXHIBIT-C-SUMMARY",
            case_id=case_id,
            doc_type="agent_generated",
            title="Exhibit C - Misrepresented Inspection Evidence",
            text=exhibit_c_text,
            date=now_iso,
            tags=["exhibit_packet", "evidence_chain", "contradiction_chain"],
            edges=[
                {"target": ESTIMATE_ID, "relation": "contradicts"},
                {"target": GERBER_ID, "relation": "supports"}
            ]
        )
        print("âœ… Ingested AGENT-EXHIBIT-C-SUMMARY")
    except ValueError as e:
        print(f"â„¹ï¸ Skipping AGENT-EXHIBIT-C-SUMMARY: {e}")

    print("\nâœ… Graph reasoning upgrade complete.")

if __name__ == "__main__":
    CASE_ID = "YOUR-CASE-ID"
    apply_updates(CASE_ID)
