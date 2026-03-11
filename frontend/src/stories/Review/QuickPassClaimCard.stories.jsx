import { QuickPassClaimCard, claimTypeColors } from "../../pages/Review";
import { fn } from "storybook/test";

export default {
  title: "Review/QuickPassClaimCard",
  component: QuickPassClaimCard,
  parameters: { layout: "padded" },
  args: {
    onApprove: fn(),
    onDismiss: fn(),
    onEdit: fn(),
    onFlag: fn(),
    onEditChange: fn(),
    onEditSave: fn(),
    onEditCancel: fn(),
    isEditing: false,
    editText: "",
  },
};

const baseClaim = {
  id: 1,
  claim_type: "fact",
  claim_text: "The CFTC is expected to finalize the position limits rule by Q3 2026.",
  confidence: 0.87,
  subject_name: "Sarah Chen",
  episode_title: "Weekly derivatives sync",
  evidence_quote: "Sarah said she heard from legal that position limits will be done by end of Q3.",
};

export const Focused = {
  args: {
    claim: baseClaim,
    isFocused: true,
  },
};

export const Unfocused = {
  args: {
    claim: baseClaim,
    isFocused: false,
  },
};

export const Commitment = {
  args: {
    claim: {
      ...baseClaim,
      claim_type: "commitment",
      claim_text: "Will send the updated compliance framework by Friday.",
      firmness: "firm",
      direction: "speaker_to_subject",
      has_deadline: true,
      has_condition: false,
    },
    isFocused: true,
  },
};

export const Editing = {
  args: {
    claim: baseClaim,
    isFocused: true,
    isEditing: true,
    editText: "The CFTC is expected to finalize the position limits rule by Q3 2026.",
  },
};

export const LongText = {
  args: {
    claim: {
      ...baseClaim,
      claim_text: "This is a very long claim text that represents a complex regulatory position involving multiple stakeholders, cross-agency coordination, and detailed technical analysis of derivatives market structure reform proposals that span several paragraphs of discussion.",
      evidence_quote: "During the extended discussion about market structure reform, the participant elaborated at length on the complexities of cross-border derivatives regulation and the challenges of harmonizing US and EU approaches to position limits, margin requirements, and trade reporting obligations.",
    },
    isFocused: true,
  },
};

export const AllTypes = {
  name: "All claim types",
  render: (args) => (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {Object.keys(claimTypeColors).map((type, i) => (
        <QuickPassClaimCard
          key={type}
          claim={{ ...baseClaim, id: i, claim_type: type, claim_text: `Sample ${type} claim.` }}
          isFocused={i === 0}
          {...args}
        />
      ))}
    </div>
  ),
};
