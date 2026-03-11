import StatCard from "../../components/StatCard";

export default {
  title: "Components/StatCard",
  component: StatCard,
  parameters: {
    layout: "padded",
    backgrounds: { default: "sauron-dark" },
  },
};

export const Default = {
  args: {
    label: "Active claims",
    value: 142,
    sub: "across 23 conversations",
  },
};

export const WithColor = {
  args: {
    label: "Failed routes",
    value: 7,
    sub: "needs attention",
    color: "#ef4444",
  },
};

export const LargeValue = {
  args: {
    label: "Total processed",
    value: "1,847",
    sub: "since deployment",
    color: "#10b981",
  },
};

export const NoSub = {
  args: {
    label: "Pending",
    value: 3,
  },
};
