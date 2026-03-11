import { fn } from "storybook/test";
import { C, cardStyle } from "../../pages/ConversationDetail";
import {
  contacts, linkedEntities, reassignPreview, reassignResult,
} from "../review-fixtures";

/**
 * BulkReassignModal has internal state + API calls.
 * We render static snapshots of each step for visual testing.
 */

function ModalShell({ children }) {
  return (
    <div style={{ position: "relative", background: "rgba(0,0,0,0.6)", padding: 40, minHeight: 400, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{ ...cardStyle, width: 520, maxHeight: "80vh", overflow: "auto" }}>
        {children}
      </div>
    </div>
  );
}

function InitialStep({ linkedEntities: linked, selectedFrom, selectedTo }) {
  return (
    <ModalShell>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <h2 style={{ fontSize: 16, fontWeight: 600, color: C.text }}>Bulk Reassign Speaker</h2>
        <button style={{ background: "none", border: "none", color: C.textDim, fontSize: 18, cursor: "pointer" }}>&times;</button>
      </div>
      <div style={{ marginBottom: 16 }}>
        <label style={{ fontSize: 12, color: C.textMuted, display: "block", marginBottom: 6 }}>Reassign all references from:</label>
        <select value={selectedFrom || ""} readOnly
          style={{ width: "100%", padding: "8px 10px", background: C.bg, border: `1px solid ${C.border}`, borderRadius: 4, color: C.text, fontSize: 13 }}>
          <option value="">Select entity...</option>
          {Object.entries(linked).map(([eId, eName]) => (
            <option key={eId} value={eId}>{eName}</option>
          ))}
        </select>
      </div>
      <div style={{ marginBottom: 16 }}>
        <label style={{ fontSize: 12, color: C.textMuted, display: "block", marginBottom: 6 }}>Reassign to:</label>
        {selectedTo ? (
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span style={{ fontSize: 13, color: C.text, padding: "8px 10px", background: C.bg, border: `1px solid ${C.border}`, borderRadius: 4, flex: 1 }}>
              {selectedTo}
            </span>
            <button style={{ fontSize: 12, color: C.textDim, background: "none", border: `1px solid ${C.border}`, borderRadius: 4, padding: "6px 10px", cursor: "pointer" }}>Change</button>
          </div>
        ) : (
          <input placeholder="Search contacts..." readOnly
            style={{ width: "100%", padding: "8px 10px", background: C.bg, border: `1px solid ${C.border}`, borderRadius: 4, color: C.text, fontSize: 13, outline: "none" }} />
        )}
      </div>
      <div style={{ marginBottom: 16 }}>
        <label style={{ fontSize: 12, color: C.textMuted, display: "block", marginBottom: 6 }}>Scope:</label>
        <div style={{ display: "flex", gap: 8 }}>
          {["All", "Claims only", "Transcript only"].map((s, i) => (
            <button key={s} style={{ padding: "6px 12px", borderRadius: 4, fontSize: 12, cursor: "pointer", border: "none",
              background: i === 0 ? C.accent : `${C.accent}15`, color: i === 0 ? "#fff" : C.textMuted }}>{s}</button>
          ))}
        </div>
      </div>
      <button disabled={!selectedFrom || !selectedTo}
        style={{ width: "100%", padding: "10px 16px", background: `${C.accent}22`, color: C.accent,
          border: `1px solid ${C.accent}44`, borderRadius: 6, fontSize: 13, cursor: "pointer",
          opacity: (!selectedFrom || !selectedTo) ? 0.5 : 1 }}>
        Preview Changes
      </button>
    </ModalShell>
  );
}

function PreviewStep({ preview, nameOverride }) {
  return (
    <ModalShell>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <h2 style={{ fontSize: 16, fontWeight: 600, color: C.text }}>Bulk Reassign Speaker</h2>
        <button style={{ background: "none", border: "none", color: C.textDim, fontSize: 18, cursor: "pointer" }}>&times;</button>
      </div>
      {nameOverride && (
        <div style={{ marginBottom: 12, padding: 8, borderRadius: 4, background: C.accent + "10", border: `1px solid ${C.accent}33` }}>
          <span style={{ fontSize: 12, color: C.accent }}>Display name override: <strong>{nameOverride}</strong></span>
        </div>
      )}
      <div style={{ padding: 12, borderRadius: 6, background: `${C.warning}10`, border: `1px solid ${C.warning}33`, marginBottom: 12 }}>
        <p style={{ fontSize: 13, fontWeight: 600, color: C.warning, marginBottom: 4 }}>Preview: {preview.from_entity} &rarr; {preview.to_entity}</p>
        <div style={{ fontSize: 12, color: C.textMuted }}>
          <p>{preview.claims_affected} claims will be reassigned</p>
          <p>{preview.transcript_segments_affected} transcript segments will be updated</p>
          <p>{preview.belief_evidence_links_affected} belief evidence links affected</p>
        </div>
      </div>
      {preview.sample_claims?.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <p style={{ fontSize: 11, color: C.textDim, marginBottom: 6, textTransform: "uppercase", fontWeight: 600 }}>Sample changes:</p>
          {preview.sample_claims.map((sc, i) => (
            <div key={i} style={{ fontSize: 12, padding: "6px 0", borderBottom: `1px solid ${C.border}` }}>
              <span style={{ color: C.danger, textDecoration: "line-through" }}>{sc.old_subject}</span>
              {" \u2192 "}
              <span style={{ color: C.success }}>{sc.new_subject}</span>
              <p style={{ color: C.textDim, marginTop: 2, fontSize: 11 }}>{sc.claim_text}</p>
            </div>
          ))}
        </div>
      )}
      <div style={{ display: "flex", gap: 8 }}>
        <button style={{ flex: 1, padding: "10px 16px", background: "transparent", color: C.textMuted, border: `1px solid ${C.border}`, borderRadius: 6, fontSize: 13, cursor: "pointer" }}>Cancel</button>
        <button style={{ flex: 1, padding: "10px 16px", background: C.danger, color: "#fff", border: "none", borderRadius: 6, fontSize: 13, cursor: "pointer" }}>
          Reassign {preview.claims_affected} Claims
        </button>
      </div>
    </ModalShell>
  );
}

function CompleteStep({ result }) {
  return (
    <ModalShell>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <h2 style={{ fontSize: 16, fontWeight: 600, color: C.text }}>Bulk Reassign Speaker</h2>
        <button style={{ background: "none", border: "none", color: C.textDim, fontSize: 18, cursor: "pointer" }}>&times;</button>
      </div>
      <div style={{ padding: 16, borderRadius: 6, background: `${C.success}15`, border: `1px solid ${C.success}33`, marginBottom: 16 }}>
        <p style={{ fontSize: 14, fontWeight: 600, color: C.success, marginBottom: 8 }}>Reassignment Complete</p>
        <p style={{ fontSize: 13, color: C.text }}>{result.from_entity} &rarr; {result.to_entity}</p>
        <div style={{ fontSize: 12, color: C.textMuted, marginTop: 8 }}>
          <p>{result.claims_updated} claims updated</p>
          <p>{result.transcripts_updated} transcript segments updated</p>
          <p>{result.beliefs_invalidated} beliefs set to under_review</p>
          {result.ambiguous_claims_flagged > 0 && (
            <p style={{ color: C.amber || C.warning }}>{result.ambiguous_claims_flagged} claims flagged as ambiguous</p>
          )}
        </div>
        {result.transcript_review_recommended && (
          <p style={{ fontSize: 12, color: C.warning, marginTop: 8 }}>
            Transcript speaker labels were also updated. Review the Transcript tab to verify.
          </p>
        )}
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        {result.transcript_review_recommended && (
          <button style={{ flex: 1, padding: "10px 16px", background: `${C.warning}22`, color: C.warning, border: `1px solid ${C.warning}44`, borderRadius: 6, fontSize: 13, cursor: "pointer" }}>
            Review Transcript
          </button>
        )}
        <button style={{ flex: 1, padding: "10px 16px", background: C.accent, color: "#fff", border: "none", borderRadius: 6, fontSize: 13, cursor: "pointer" }}>
          Close & Refresh
        </button>
      </div>
    </ModalShell>
  );
}

export default {
  title: "Review/BulkReassignModal",
  parameters: { layout: "fullscreen" },
};

export const Initial = {
  render: () => <InitialStep linkedEntities={linkedEntities} />,
};

export const WithSelections = {
  name: "Initial — with selections made",
  render: () => <InitialStep linkedEntities={linkedEntities} selectedFrom="c-001" selectedTo="Amy Liu" />,
};

export const Preview = {
  render: () => <PreviewStep preview={reassignPreview} />,
};

export const PreviewWithNameOverride = {
  name: "Preview — with display name override",
  render: () => <PreviewStep preview={reassignPreview} nameOverride="A. Liu" />,
};

export const Complete = {
  render: () => <CompleteStep result={reassignResult} />,
};

export const CompleteNoTranscriptReview = {
  name: "Complete — no transcript review needed",
  render: () => <CompleteStep result={{ ...reassignResult, transcript_review_recommended: false, ambiguous_claims_flagged: 0 }} />,
};
