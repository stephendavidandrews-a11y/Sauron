import { fn } from "storybook/test";
import { CommitmentEditPanel } from "../../pages/ConversationDetail";
import { claimCommitment, claimConditionalCommitment, makeClaim } from "../review-fixtures";

// CommitmentEditPanel calls api.correctClaimBatch on save; this will fail
// silently in stories. The panel itself renders fine regardless.

export default {
  title: "Review/CommitmentEditPanel",
  component: CommitmentEditPanel,
  parameters: { layout: "padded" },
  args: {
    conversationId: "conv-001",
    onSave: fn(),
    onCancel: fn(),
  },
};

export const FirmCommitment = {
  name: "Firm commitment (concrete, has deadline)",
  args: {
    claim: claimCommitment,
  },
};

export const TentativeCommitment = {
  name: "Tentative commitment (has condition)",
  args: {
    claim: claimConditionalCommitment,
  },
};

export const Blank = {
  name: "Blank (no commitment fields set)",
  args: {
    claim: makeClaim({
      id: 501,
      claim_type: "commitment",
      claim_text: "Will follow up on the regulatory guidance.",
      firmness: null,
      direction: null,
      has_deadline: false,
      has_condition: false,
      has_specific_action: false,
      condition_text: null,
      time_horizon: null,
    }),
  },
};
