import { RoutingStatusBar } from "../../pages/Today";

export default {
  title: "Today/RoutingStatusBar",
  component: RoutingStatusBar,
  parameters: { layout: "padded" },
};

export const AllIndicators = {
  args: {
    routing: { failed_count: 3, pending_entity_count: 7, sent_count: 15 },
  },
};

export const FailedOnly = {
  args: {
    routing: { failed_count: 2, pending_entity_count: 0, sent_count: 0 },
  },
};

export const PendingOnly = {
  args: {
    routing: { failed_count: 0, pending_entity_count: 4, sent_count: 0 },
  },
};

export const Hidden = {
  name: "Hidden (all zero)",
  args: {
    routing: { failed_count: 0, pending_entity_count: 0, sent_count: 0 },
  },
};

export const NullRouting = {
  name: "Null routing prop",
  args: { routing: null },
};
