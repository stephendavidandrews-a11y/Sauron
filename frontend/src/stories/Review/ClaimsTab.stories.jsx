import { fn } from "storybook/test";
import { ClaimsTab } from "../../pages/ConversationDetail";
import {
  contacts,
  allClaims,
  claimApproved,
  claimDismissed,
  claimDeferred,
  claimCorrected,
  claimFact,
  makeClaim,
} from "../review-fixtures";

export default {
  title: "Review/ClaimsTab",
  component: ClaimsTab,
  parameters: { layout: "padded" },
};

const updateClaim = fn();

export const Normal = {
  name: "Normal (all claims)",
  args: {
    claims: allClaims,
    conversationId: "conv-001",
    contacts,
    updateClaim,
  },
};

export const MixedReviewStates = {
  name: "Mixed review states",
  args: {
    claims: [
      claimApproved,
      claimDismissed,
      claimDeferred,
      claimCorrected,
      makeClaim({ id: 301, claim_type: "fact", claim_text: "Pending unreviewed claim." }),
    ],
    conversationId: "conv-001",
    contacts,
    updateClaim,
  },
};

export const Empty = {
  args: {
    claims: [],
    conversationId: "conv-001",
    contacts,
    updateClaim,
  },
};

export const SingleClaim = {
  args: {
    claims: [claimFact],
    conversationId: "conv-001",
    contacts,
    updateClaim,
  },
};
