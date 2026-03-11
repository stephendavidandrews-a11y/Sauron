import { WhatChangedCard } from "../../pages/Today";

export default {
  title: "Today/WhatChangedCard",
  component: WhatChangedCard,
  parameters: { layout: "padded" },
};

const makeBelief = (overrides = {}) => ({
  entity_name: "John Smith",
  belief_summary: "Believes the new derivatives regulation will be finalized by Q3.",
  confidence: 0.82,
  status: "active",
  last_changed_at: new Date(Date.now() - 3600000).toISOString(),
  ...overrides,
});

export const Normal = {
  args: {
    beliefs: [
      makeBelief(),
      makeBelief({ entity_name: "Sarah Chen", status: "contested", confidence: 0.55, belief_summary: "Thinks the CFTC will expand swap dealer definitions significantly." }),
      makeBelief({ entity_name: "Mark Weber", status: "provisional", confidence: 0.71, belief_summary: "Position clearing requirements may be reduced under new leadership." }),
    ],
  },
};

export const Empty = {
  args: { beliefs: [] },
};

export const ManyItems = {
  args: {
    beliefs: Array.from({ length: 12 }, (_, i) =>
      makeBelief({
        entity_name: `Person ${i + 1}`,
        belief_summary: `Belief statement number ${i + 1} about regulatory policy changes and their expected impact.`,
        status: ["active", "contested", "provisional", "qualified"][i % 4],
        confidence: 0.5 + Math.random() * 0.5,
        last_changed_at: new Date(Date.now() - i * 7200000).toISOString(),
      })
    ),
  },
};

export const LongText = {
  args: {
    beliefs: [
      makeBelief({
        entity_name: "Alexandra Richardson-Montgomery",
        belief_summary: "This is a very long belief summary that should be truncated because it exceeds the 100-character limit imposed by the component rendering logic which clips text and adds an ellipsis to prevent overflow.",
        status: "under_review",
        confidence: 0.93,
      }),
    ],
  },
};
