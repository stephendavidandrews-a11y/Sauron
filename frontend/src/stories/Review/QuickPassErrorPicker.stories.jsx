import { QuickPassErrorPicker } from "../../components/review/quickpass/QuickPassErrorPicker";
import { fn } from "storybook/test";

export default {
  title: "Review/QuickPassErrorPicker",
  component: QuickPassErrorPicker,
  parameters: { layout: "padded" },
};

export const Default = {
  args: {
    onSelect: fn(),
    onCancel: fn(),
  },
};
