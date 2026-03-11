import { QuickPassProposalCard } from "../../pages/Review";
import { fn } from "storybook/test";

export default {
  title: "Review/QuickPassProposalCard",
  component: QuickPassProposalCard,
  parameters: { layout: "padded" },
};

const baseProposal = {
  id: 1,
  entity_name: "John Smith",
  belief_key: "position_on_swap_regulation",
  current_status: "provisional",
  proposed_status: "active",
  proposed_summary: "John firmly supports expanding swap dealer definitions to cover more market participants.",
  reasoning: "Three independent conversations over the past month have confirmed this stance with high confidence.",
};

export const Focused = {
  args: {
    proposal: baseProposal,
    isFocused: true,
    onAccept: fn(),
    onReject: fn(),
  },
};

export const Unfocused = {
  args: {
    proposal: baseProposal,
    isFocused: false,
    onAccept: fn(),
    onReject: fn(),
  },
};

export const LongReasoning = {
  args: {
    proposal: {
      ...baseProposal,
      proposed_summary: "After extensive analysis of multiple data points across several conversations spanning the past quarter, the evidence strongly suggests a shift in position from cautious skepticism to active advocacy for comprehensive market structure reform, including expanded clearing mandates and stricter position limits for speculative traders in energy and agricultural commodity derivatives markets.",
      reasoning: "This conclusion is drawn from corroborating evidence across five separate conversations, including two formal meetings and three informal discussions, where the subject consistently emphasized the need for broader regulatory oversight and expressed increasing frustration with the current exemption framework.",
    },
    isFocused: true,
    onAccept: fn(),
    onReject: fn(),
  },
};
