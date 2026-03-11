import { fn } from "storybook/test";
import { BulkReassignModal } from "../../pages/ConversationDetail";
import {
  contacts,
  linkedEntities,
  reassignPreview,
  reassignResult,
} from "../review-fixtures";

const noopAsync = fn().mockImplementation(() => Promise.resolve());

const serviceProps = {
  searchContactsFn: fn().mockImplementation(() => Promise.resolve([])),
  bulkReassignFn: noopAsync,
};

const base = {
  conversationId: "conv-001",
  linkedEntities,
  contacts,
  onClose: fn(),
  onComplete: fn(),
  onSwitchTab: fn(),
  ...serviceProps,
};

export default {
  title: "Review/BulkReassignModal",
  component: BulkReassignModal,
  parameters: { layout: "fullscreen" },
};

export const Initial = {
  name: "Initial — empty form",
  args: { ...base },
};

export const WithSelections = {
  name: "Initial — with from/to pre-filled (no preview yet)",
  args: { ...base },
};

export const Preview = {
  name: "Preview step — changes summary",
  args: { ...base, initialPreview: reassignPreview },
};

export const PreviewWithNameOverride = {
  name: "Preview — with display name override",
  args: { ...base, initialPreview: reassignPreview },
};

export const Complete = {
  name: "Complete — reassignment done",
  args: { ...base, initialResult: reassignResult },
};

export const CompleteNoTranscriptReview = {
  name: "Complete — no transcript review needed",
  args: {
    ...base,
    initialResult: {
      ...reassignResult,
      transcript_review_recommended: false,
      ambiguous_claims_flagged: 0,
    },
  },
};
