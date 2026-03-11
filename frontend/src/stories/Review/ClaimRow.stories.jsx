import { fn } from "storybook/test";
import {
  ClaimRow, ClaimTextWithOverrides, EntityChips, ErrorTypeDropdown,
} from "../../pages/ConversationDetail";
import {
  contacts, episodes,
  claimFact, claimPosition, claimCommitment, claimConditionalCommitment,
  claimRelationship, claimNoEntities, claimLowConfidence, claimEntityMismatch,
  claimWithOverrides, claimLongText, claimApproved, claimCorrected,
  claimDismissed, claimDeferred,
} from "../review-fixtures";

const actions = {
  onApprove: fn(),
  onDefer: fn(),
  onDismiss: fn(),
  onEdit: fn(),
  onStartEdit: fn(),
  onCancelEdit: fn(),
  onEditTextChange: fn(),
  onEntityLink: fn(),
  onRemoveEntity: fn(),
  onDismissRelink: fn(),
  onBatchCorrect: fn(),
  onReassign: fn(),
};

const defaults = {
  conversationId: "conv-001",
  isReviewed: false,
  isDismissed: false,
  isDeferred: false,
  isEditing: false,
  editText: "",
  showRelinkPrompt: false,
  contacts,
  episodes,
  ...actions,
};

export default {
  title: "Review/ClaimRow",
  component: ClaimRow,
  parameters: { layout: "padded" },
  args: defaults,
};

export const Unreviewed = {
  args: { claim: claimFact },
};

export const Approved = {
  args: { claim: claimApproved, isReviewed: true },
};

export const Corrected = {
  args: { claim: claimCorrected, isReviewed: true },
};

export const Dismissed = {
  args: {
    claim: claimDismissed,
    isDismissed: "hallucinated_claim",
  },
};

export const Deferred = {
  args: { claim: claimDeferred, isDeferred: true },
};

export const EditingText = {
  args: {
    claim: claimFact,
    isEditing: true,
    editText: "The CFTC is expected to finalize position limits by Q4 2026.",
  },
};

export const CommitmentWithFields = {
  name: "Commitment (sub-fields visible)",
  args: { claim: claimCommitment },
};

export const ConditionalCommitment = {
  args: { claim: claimConditionalCommitment },
};

export const WithEvidenceQuote = {
  args: { claim: claimFact },
};

export const WithMultipleEntities = {
  name: "Multiple entity chips",
  args: { claim: claimRelationship },
};

export const NoLinkedEntities = {
  args: { claim: claimNoEntities },
};

export const EntityTextMismatch = {
  name: "Entity-text mismatch warning",
  args: { claim: claimEntityMismatch },
};

export const RelinkPrompt = {
  name: "Re-link prompt after text edit",
  args: { claim: claimFact, showRelinkPrompt: true },
};

export const LongText = {
  args: { claim: claimLongText },
};

export const OverrideHighlighting = {
  name: "Claim text with override highlighting",
  args: { claim: claimWithOverrides },
};

export const LowConfidence = {
  args: { claim: claimLowConfidence },
};

export const PositionClaim = {
  args: { claim: claimPosition },
};

export const AllClaimTypes = {
  name: "All 7 claim types side by side",
  render: (args) => (
    <div style={{ display: "flex", flexDirection: "column" }}>
      {["fact", "position", "commitment", "preference", "relationship", "observation", "tactical"].map(
        (type, i) => (
          <ClaimRow
            key={type}
            {...defaults}
            claim={{
              ...claimFact,
              id: 200 + i,
              claim_type: type,
              claim_text: `Sample ${type} claim for visual comparison.`,
            }}
          />
        )
      )}
    </div>
  ),
};

export const FourReviewStates = {
  name: "Four review states compared",
  render: () => (
    <div style={{ display: "flex", flexDirection: "column" }}>
      <ClaimRow {...defaults} claim={{ ...claimFact, id: 301 }} />
      <ClaimRow {...defaults} claim={claimApproved} isReviewed={true} />
      <ClaimRow {...defaults} claim={claimCorrected} isReviewed={true} />
      <ClaimRow {...defaults} claim={claimDismissed} isDismissed="hallucinated_claim" />
      <ClaimRow {...defaults} claim={claimDeferred} isDeferred={true} />
    </div>
  ),
};
