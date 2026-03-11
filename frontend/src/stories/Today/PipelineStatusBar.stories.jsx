import { PipelineStatusBar } from "../../pages/Today";

export default {
  title: "Today/PipelineStatusBar",
  component: PipelineStatusBar,
  parameters: { layout: "padded" },
};

export const BothActive = {
  args: { processing: 2, pending: 5 },
};

export const OnlyProcessing = {
  args: { processing: 3, pending: 0 },
};

export const OnlyPending = {
  args: { processing: 0, pending: 4 },
};

export const Hidden = {
  name: "Hidden (all zero)",
  args: { processing: 0, pending: 0 },
};
