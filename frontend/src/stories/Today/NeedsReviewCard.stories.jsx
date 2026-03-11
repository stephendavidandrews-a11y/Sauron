import { NeedsReviewCard } from "../../pages/Today";

export default {
  title: "Today/NeedsReviewCard",
  component: NeedsReviewCard,
  parameters: { layout: "padded" },
};

export const HasItems = {
  args: { count: 7 },
};

export const SingleItem = {
  args: { count: 1 },
};

export const AllCaughtUp = {
  args: { count: 0 },
};

export const ManyItems = {
  args: { count: 42 },
};
