import { CommitmentsCard } from "../../pages/Today";

export default {
  title: "Today/CommitmentsCard",
  component: CommitmentsCard,
  parameters: { layout: "padded" },
};

const makeCommitment = (overrides = {}) => ({
  claim_text: "Will send the updated compliance framework by Friday.",
  subject_name: "Sarah Chen",
  confidence: 0.88,
  evidence_quote: "I will get that compliance framework to you by end of day Friday.",
  captured_at: new Date(Date.now() - 86400000).toISOString(),
  ...overrides,
});

export const BothSides = {
  args: {
    mine: [
      makeCommitment({ claim_text: "Follow up with legal on swap dealer exemptions." }),
      makeCommitment({ claim_text: "Review draft position limits analysis.", subject_name: "Mark Weber" }),
    ],
    theirs: [
      makeCommitment({ claim_text: "Send quarterly enforcement summary.", subject_name: "David Kim" }),
    ],
  },
};

export const OnlyMine = {
  args: {
    mine: [
      makeCommitment({ claim_text: "Draft the interagency memo for Treasury meeting." }),
      makeCommitment({ claim_text: "Share the updated org chart.", subject_name: "Lisa Park" }),
    ],
    theirs: [],
  },
};

export const OnlyTheirs = {
  args: {
    mine: [],
    theirs: [
      makeCommitment({ claim_text: "Provide cost-benefit analysis.", subject_name: "John Smith" }),
      makeCommitment({ claim_text: "Schedule the working group call.", subject_name: "Amy Liu" }),
    ],
  },
};

export const EmptyState = {
  name: "Empty",
  args: { mine: [], theirs: [] },
};

export const ManyItems = {
  args: {
    mine: Array.from({ length: 8 }, (_, i) =>
      makeCommitment({
        claim_text: `My commitment item number ${i + 1} that needs to be tracked and completed.`,
        subject_name: `Person ${i + 1}`,
        confidence: 0.6 + Math.random() * 0.35,
        captured_at: new Date(Date.now() - i * 43200000).toISOString(),
      })
    ),
    theirs: Array.from({ length: 4 }, (_, i) =>
      makeCommitment({
        claim_text: `Their commitment item number ${i + 1} that was promised.`,
        subject_name: `Other ${i + 1}`,
        captured_at: new Date(Date.now() - i * 86400000).toISOString(),
      })
    ),
  },
};
