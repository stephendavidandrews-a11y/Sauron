import { fn } from "storybook/test";
import { C, cardStyle } from "../../pages/ConversationDetail";
import { contacts, relationalClaims, relationalClaimsResolved } from "../review-fixtures";

/**
 * RelationalReferencesBanner has internal state + API calls.
 * We render static snapshots of each visual state for testing.
 */

function BannerShell({ count, children }) {
  return (
    <div style={{
      ...cardStyle, marginBottom: 16,
      borderColor: '#ec4899' + '66',
      background: '#ec4899' + '0a',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <span style={{ fontSize: 16 }}>🔗</span>
        <span style={{ color: '#ec4899', fontWeight: 600, fontSize: 14 }}>
          Relational References ({count})
        </span>
        <span style={{ color: C.textDim, fontSize: 12 }}>
          — People mentioned by relationship that need linking to contacts
        </span>
      </div>
      {children}
    </div>
  );
}

function ClaimCard({ claim, linking, linked, anchorEditing, children }) {
  return (
    <div style={{
      padding: '10px 12px', marginBottom: 8,
      background: C.card, borderRadius: 6, border: '1px solid ' + C.border,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ flex: 1 }}>
          <span style={{ color: '#ec4899', fontSize: 12, fontWeight: 600 }}>
            {claim.anchor_name && !['my','his','her','their'].includes((claim.anchor_reference || '').toLowerCase())
              ? (claim.anchor_reference || claim.anchor_name) + "'s " : ''}
            {claim.relationship_type || 'relationship'}
          </span>
          {claim.is_plural && (
            <span style={{ color: C.warning, marginLeft: 6, fontSize: 11, fontWeight: 600 }}>
              (multiple — link each person)
            </span>
          )}
          {claim.anchor_name ? (
            <span style={{ color: C.textDim, fontSize: 11, marginLeft: 8, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              anchor: {claim.anchor_name}
              <button style={{ fontSize: 10, background: 'none', border: 'none', color: C.accent, cursor: 'pointer', padding: '0 2px' }}
                title="Edit anchor">{anchorEditing ? '\u2716' : '\u270E'}</button>
            </span>
          ) : (
            <button style={{ fontSize: 11, color: C.accent, background: 'none', border: 'none', cursor: 'pointer', marginLeft: 8 }}>
              set anchor
            </button>
          )}

          {/* Anchor edit search (shown when anchorEditing) */}
          {anchorEditing && (
            <div style={{ marginTop: 6, padding: 6, background: C.bg, borderRadius: 4 }}>
              <input value="Sarah"
                readOnly
                placeholder="Search for anchor person..."
                style={{ width: '100%', padding: '4px 8px', fontSize: 12, borderRadius: 3,
                  background: C.card, color: C.text, border: '1px solid ' + C.border, outline: 'none', boxSizing: 'border-box' }} />
              {contacts.slice(0, 3).map(c => (
                <div key={c.id}
                  style={{ padding: '4px 8px', fontSize: 12, color: C.text, cursor: 'pointer', borderRadius: 3 }}>
                  {c.canonical_name}
                </div>
              ))}
            </div>
          )}

          <div style={{ fontSize: 12, color: C.textMuted, marginTop: 4 }}>
            {claim.claim_text?.slice(0, 140)}{claim.claim_text?.length > 140 ? '...' : ''}
          </div>

          {/* Already-linked people */}
          {linked && linked.length > 0 && (
            <div style={{ marginTop: 6, display: 'flex', gap: 4, flexWrap: 'wrap' }}>
              {linked.map((p, i) => (
                <span key={i} style={{
                  fontSize: 11, padding: '2px 8px', borderRadius: 10,
                  background: C.success + '22', color: C.success,
                }}>✓ {p.name}</span>
              ))}
            </div>
          )}
        </div>

        <button style={{
          padding: '4px 10px', fontSize: 12, borderRadius: 4, cursor: 'pointer',
          background: '#ec4899' + '22', color: '#ec4899',
          border: '1px solid ' + '#ec4899' + '44', whiteSpace: 'nowrap',
        }}>
          {claim.is_plural ? 'Link Person' : 'Link'}
        </button>
      </div>

      {/* Search dropdown */}
      {linking && (
        <div style={{ marginTop: 8, padding: 8, background: C.bg, borderRadius: 4 }}>
          <input
            type="text" placeholder="Search contacts..."
            value="Mark" readOnly
            style={{
              width: '100%', padding: '6px 10px', fontSize: 13, borderRadius: 4,
              background: C.card, color: C.text, border: '1px solid ' + C.border,
              outline: 'none', boxSizing: 'border-box',
            }}
          />
          <div style={{ marginTop: 4, maxHeight: 150, overflowY: 'auto' }}>
            {contacts.filter(c => c.canonical_name.toLowerCase().includes('mark') || c.canonical_name.toLowerCase().includes('m')).slice(0, 4).map(c => (
              <div key={c.id}
                style={{
                  padding: '6px 10px', cursor: 'pointer', fontSize: 13,
                  color: C.text, borderRadius: 4,
                }}>
                {c.canonical_name}
                {c.email && <span style={{ color: C.textDim, marginLeft: 8, fontSize: 11 }}>{c.email}</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      {children}
    </div>
  );
}

function RelPromptUI({ anchorName, relationship, targetName, targets }) {
  const allTargets = targets || [{ name: targetName }];
  return (
    <div style={{
      padding: '14px 16px', marginBottom: 10, borderRadius: 6,
      background: C.success + '08', border: '1px solid ' + C.success + '33',
    }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: C.success, marginBottom: 10 }}>
        Save Relationship
      </div>
      <div style={{ marginBottom: 8 }}>
        <label style={{ fontSize: 11, color: C.textDim, display: 'block', marginBottom: 3 }}>Relationship Type</label>
        <input value={relationship} readOnly
          style={{ width: '100%', padding: '5px 8px', fontSize: 13, borderRadius: 4,
            background: C.bg, color: C.text, border: '1px solid ' + C.border, outline: 'none', boxSizing: 'border-box' }}
          placeholder="e.g., son, birth mother, colleague" />
      </div>
      <div style={{ marginBottom: 8 }}>
        <label style={{ fontSize: 11, color: C.textDim, display: 'block', marginBottom: 3 }}>Source Person (who has this relationship)</label>
        <div style={{ fontSize: 13, color: '#ec4899', fontWeight: 500, padding: '5px 8px',
          background: C.card, borderRadius: 4, border: '1px solid ' + C.border }}>
          {anchorName}
        </div>
      </div>
      <div style={{ marginBottom: 10 }}>
        <label style={{ fontSize: 11, color: C.textDim, display: 'block', marginBottom: 3 }}>Related To (target person)</label>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 6 }}>
          {allTargets.map((t, i) => (
            <span key={i} style={{
              fontSize: 12, padding: '3px 8px', borderRadius: 4,
              background: '#ec4899' + '22', color: '#ec4899', display: 'inline-flex', alignItems: 'center', gap: 4,
            }}>
              {t.name}
              {allTargets.length > 1 && (
                <button style={{ fontSize: 10, background: 'none', border: 'none', color: C.textDim, cursor: 'pointer', padding: 0 }}>&times;</button>
              )}
            </span>
          ))}
        </div>
        <button style={{ fontSize: 11, padding: '3px 8px', borderRadius: 4, cursor: 'pointer',
          background: 'transparent', color: C.accent, border: '1px solid ' + C.accent + '44' }}>
          + Add another person
        </button>
      </div>
      <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
        <button style={{
          padding: '6px 14px', fontSize: 12, borderRadius: 4, cursor: 'pointer',
          background: C.success + '22', color: C.success, border: '1px solid ' + C.success + '44', fontWeight: 500,
        }}>Save Relationship</button>
        <button style={{
          padding: '6px 14px', fontSize: 12, borderRadius: 4, cursor: 'pointer',
          background: C.card, color: C.textDim, border: '1px solid ' + C.border,
        }}>Skip</button>
      </div>
    </div>
  );
}

export default {
  title: "Review/RelationalReferencesBanner",
  parameters: { layout: "padded" },
};

export const UnresolvedClaims = {
  name: "Unresolved relational claims",
  render: () => (
    <BannerShell count={2}>
      {relationalClaims.map(c => (
        <ClaimCard key={c.id} claim={c} />
      ))}
    </BannerShell>
  ),
};

export const WithSearchOpen = {
  name: "Link search open",
  render: () => (
    <BannerShell count={2}>
      <ClaimCard claim={relationalClaims[0]} linking />
      <ClaimCard claim={relationalClaims[1]} />
    </BannerShell>
  ),
};

export const WithRelPrompt = {
  name: "Relationship save prompt visible",
  render: () => (
    <BannerShell count={2}>
      <RelPromptUI anchorName="Stephen Andrews" relationship="brother" targetName="Mark Weber" />
      <ClaimCard claim={relationalClaims[0]} linked={[{ name: "Mark Weber" }]} />
      <ClaimCard claim={relationalClaims[1]} />
    </BannerShell>
  ),
};

export const WithRelPromptMultiTarget = {
  name: "Relationship prompt — multiple targets",
  render: () => (
    <BannerShell count={1}>
      <RelPromptUI
        anchorName="Sarah Chen"
        relationship="colleague"
        targets={[{ name: "Mark Weber" }, { name: "Amy Liu" }]}
      />
      <ClaimCard
        claim={{ ...relationalClaims[1], is_plural: true, relationship_type: "colleagues" }}
        linked={[{ name: "Mark Weber" }, { name: "Amy Liu" }]}
      />
    </BannerShell>
  ),
};

export const PartiallyLinked = {
  name: "One claim linked, one remaining",
  render: () => (
    <BannerShell count={1}>
      <ClaimCard claim={relationalClaims[1]} />
    </BannerShell>
  ),
};

export const PluralClaim = {
  name: "Plural relational reference",
  render: () => (
    <BannerShell count={1}>
      <ClaimCard
        claim={{
          id: 202,
          claim_type: "fact",
          claim_text: "His colleagues all agree the timeline is too aggressive for full implementation.",
          subject_name: "his colleagues",
          subject_entity_id: null,
          is_relational: true,
          anchor_name: "Mark Weber",
          anchor_reference: "His",
          relationship_type: "colleagues",
          entities: [],
          is_plural: true,
        }}
        linked={[{ name: "Sarah Chen" }]}
      />
    </BannerShell>
  ),
};

export const AnchorEditing = {
  name: "Anchor edit search open",
  render: () => (
    <BannerShell count={2}>
      <ClaimCard claim={relationalClaims[0]} anchorEditing />
      <ClaimCard claim={relationalClaims[1]} />
    </BannerShell>
  ),
};

export const NoAnchor = {
  name: "Claim with no anchor set",
  render: () => (
    <BannerShell count={1}>
      <ClaimCard claim={{
        id: 203,
        claim_type: "fact",
        claim_text: "Their lawyer said the filing deadline won't hold.",
        subject_name: "their lawyer",
        subject_entity_id: null,
        is_relational: true,
        anchor_name: null,
        anchor_reference: null,
        relationship_type: "lawyer",
        entities: [],
        is_plural: false,
      }} />
    </BannerShell>
  ),
};
