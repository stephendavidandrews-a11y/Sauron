import { TodayConversationsCard } from "../../pages/Today";

export default {
  title: "Today/TodayConversationsCard",
  component: TodayConversationsCard,
  parameters: { layout: "padded" },
};

const makeConversation = (overrides = {}) => ({
  id: Math.random().toString(36).slice(2),
  manual_note: null,
  title: "Weekly sync with derivatives team",
  source: "plaud",
  duration_seconds: 1845,
  processing_status: "completed",
  captured_at: new Date(Date.now() - 3600000).toISOString(),
  ...overrides,
});

export const Normal = {
  args: {
    conversations: [
      makeConversation(),
      makeConversation({ title: "Lunch with Sarah Chen", source: "iphone", duration_seconds: 2700, processing_status: "completed" }),
      makeConversation({ title: null, source: "pi", duration_seconds: 420, processing_status: "extracting", manual_note: "Office drop-in from Mark" }),
    ],
  },
};

export const Empty = {
  args: { conversations: [] },
};

export const Processing = {
  args: {
    conversations: [
      makeConversation({ processing_status: "transcribing", duration_seconds: 900 }),
      makeConversation({ processing_status: "pending", title: "Call with legal team", duration_seconds: null }),
      makeConversation({ processing_status: "error", title: "Corrupted audio file", source: "pi" }),
      makeConversation({ processing_status: "awaiting_speaker_review", title: "Conference room discussion" }),
      makeConversation({ processing_status: "awaiting_claim_review", title: "Budget planning call" }),
    ],
  },
};

export const ManyItems = {
  args: {
    conversations: Array.from({ length: 10 }, (_, i) =>
      makeConversation({
        title: `Conversation ${i + 1}`,
        source: ["plaud", "iphone", "pi", "email"][i % 4],
        duration_seconds: 300 + i * 600,
        processing_status: ["completed", "processing", "pending", "completed"][i % 4],
        captured_at: new Date(Date.now() - i * 3600000).toISOString(),
      })
    ),
  },
};
