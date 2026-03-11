import tailwindcss from "@tailwindcss/vite";

/** @type {import("@storybook/react-vite").StorybookConfig} */
const config = {
  stories: ["../src/**/*.stories.@(js|jsx)"],
  framework: {
    name: "@storybook/react-vite",
    options: {},
  },
  async viteFinal(config) {
    const { mergeConfig } = await import("vite");
    return mergeConfig(config, {
      plugins: [tailwindcss()],
    });
  },
};

export default config;
