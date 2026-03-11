import { ClaimTextWithOverrides } from "../../pages/ConversationDetail";

// Pure component -- no API calls, no callbacks.

export default {
  title: "Review/ClaimTextWithOverrides",
  component: ClaimTextWithOverrides,
  parameters: { layout: "padded" },
};

export const NoOverrides = {
  name: "No overrides (plain text)",
  args: {
    text: "The CFTC is expected to finalize position limits by Q3 2026.",
    overrides: null,
  },
};

export const SingleOverride = {
  name: "Single override (amber highlight)",
  args: {
    text: "My brother thinks the rulemaking will stall in committee.",
    overrides: [
      { start: 0, end: 10, resolved_name: "Mark Weber" },
    ],
  },
};

export const MultipleOverrides = {
  name: "Multiple overrides (non-adjacent)",
  args: {
    text: "Her boss told my sister the proposal would not advance this quarter.",
    overrides: [
      { start: 0, end: 8, resolved_name: "Amy Liu" },
      { start: 18, end: 27, resolved_name: "Sarah Chen" },
    ],
  },
};

export const AdjacentOverrides = {
  name: "Adjacent overrides",
  args: {
    text: "He told her the filing deadline was extended to next month.",
    overrides: [
      { start: 0, end: 2, resolved_name: "David Kim" },
      { start: 8, end: 11, resolved_name: "Amy Liu" },
    ],
  },
};
