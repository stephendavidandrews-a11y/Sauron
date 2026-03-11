import { MemoryRouter } from "react-router-dom";
import "../src/index.css";

/** @type {import("@storybook/react").Preview} */
const preview = {
  parameters: {
    backgrounds: {
      default: "sauron-dark",
      values: [
        { name: "sauron-dark", value: "#0a0f1a" },
        { name: "card", value: "#111827" },
        { name: "light", value: "#ffffff" },
      ],
    },
  },
  decorators: [
    (Story) => (
      <MemoryRouter>
        <Story />
      </MemoryRouter>
    ),
  ],
};

export default preview;
