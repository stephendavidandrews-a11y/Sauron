import { fn, userEvent, within } from "storybook/test";
import { ErrorTypeDropdown } from "../../pages/ConversationDetail";
import { claimFact } from "../review-fixtures";

export default {
  title: "Review/ErrorTypeDropdown",
  component: ErrorTypeDropdown,
  parameters: { layout: "padded" },
  args: {
    claim: claimFact,
    onSelect: fn(),
  },
};

export const Closed = {
  name: "Closed (default)",
};

export const Open = {
  name: "Open (dropdown expanded)",
  parameters: {
    chromatic: { delay: 300 },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const flagBtn = canvas.getByRole("button", { name: /flag/i });
    await userEvent.click(flagBtn);
  },
};
