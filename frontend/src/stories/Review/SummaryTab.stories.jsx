import { SummaryTab } from "../../pages/ConversationDetail";
import {
  synthesis,
  beliefUpdates,
  allClaims,
  claimCommitment,
  claimConditionalCommitment,
  makeClaim,
} from "../review-fixtures";

// Pure component -- no API calls.

const emptySynthesis = {
  summary: null,
  vocal_intelligence_summary: null,
  word_voice_alignment: null,
  topics_discussed: [],
  follow_ups: [],
  self_coaching: [],
  my_commitments: [],
  contact_commitments: [],
};

export default {
  title: "Review/SummaryTab",
  component: SummaryTab,
  parameters: { layout: "padded" },
};

export const Full = {
  name: "Full (all sections populated)",
  args: {
    synthesis,
    beliefUpdates,
    claims: allClaims,
  },
};

export const MinimalSynthesis = {
  name: "Minimal synthesis (summary only, no topics or coaching)",
  args: {
    synthesis: {
      ...emptySynthesis,
      summary: "Brief discussion about regulatory timelines and compliance deliverables.",
    },
    beliefUpdates: [],
    claims: [],
  },
};

export const WithCommitments = {
  name: "With commitment claims",
  args: {
    synthesis: {
      ...emptySynthesis,
      summary: "Commitment-heavy session with clear directional obligations.",
    },
    beliefUpdates,
    claims: [
      claimCommitment,
      claimConditionalCommitment,
      makeClaim({
        id: 601,
        claim_type: "commitment",
        claim_text: "They will circulate the revised agenda before Thursday.",
        firmness: "firm",
        direction: "owed_to_me",
        has_deadline: true,
        time_horizon: "this_week",
        review_status: null,
      }),
      makeClaim({
        id: 602,
        claim_type: "commitment",
        claim_text: "Will schedule a follow-up call next week.",
        firmness: "intentional",
        direction: "mutual",
        has_deadline: false,
        review_status: "dismissed",
      }),
    ],
  },
};

export const Empty = {
  name: "Empty synthesis",
  args: {
    synthesis: emptySynthesis,
    beliefUpdates: [],
    claims: [],
  },
};
