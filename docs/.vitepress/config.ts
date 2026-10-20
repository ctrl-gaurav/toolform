import { defineConfig } from "vitepress";

// GitHub Pages serves the docs at https://ctrl-gaurav.github.io/toolform/docs/; a host serving the
// site from a domain root sets DOCS_BASE=/docs/ (and Netlify sets URL for the link home).
const BASE = process.env.DOCS_BASE || "/toolform/docs/";
const HOME = process.env.SITE_HOME || (process.env.URL ? `${process.env.URL}/` : "https://ctrl-gaurav.github.io/toolform/");

export default defineConfig({
  title: "ToolForm",
  titleTemplate: ":title · ToolForm docs",
  description: "ToolForm documentation: recommend, render, parse and guard the tool interface of an LLM agent.",
  base: BASE,
  cleanUrls: true,
  lastUpdated: false,
  head: [
    ["link", { rel: "icon", type: "image/svg+xml", href: `${BASE}favicon.svg` }],
    ["meta", { name: "theme-color", content: "#06080c" }],
    ["meta", { property: "og:title", content: "ToolForm documentation" }],
    ["meta", { property: "og:description", content: "Tool interfaces for LLM agents, chosen by measurement." }],
    ["link", { rel: "preconnect", href: "https://fonts.googleapis.com" }],
    [
      "link",
      {
        rel: "stylesheet",
        href: "https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&display=swap",
      },
    ],
  ],
  markdown: {
    theme: { light: "github-light", dark: "github-dark" },
    lineNumbers: false,
  },
  themeConfig: {
    logo: { light: "/logo-light.svg", dark: "/logo.svg" },
    logoLink: HOME, // the logo goes to the site's home page, not the docs home
    siteTitle: false,
    nav: [
      { text: "Guide", link: "/quickstart" },
      { text: "Reference", link: "/reference/sdk" },
      { text: "Dashboard ↗", link: `${HOME}#/dashboard/advisor` },
      { text: "Home ↗", link: HOME },
    ],
    sidebar: [
      {
        text: "Start",
        items: [
          { text: "What is ToolForm?", link: "/" },
          { text: "Quick start", link: "/quickstart" },
          { text: "Concepts", link: "/concepts" },
          { text: "The evidence", link: "/evidence" },
        ],
      },
      {
        text: "Guides",
        items: [
          { text: "Choose a format", link: "/guides/choose-a-format" },
          { text: "Render and parse", link: "/guides/render-and-parse" },
          { text: "Validate arguments", link: "/guides/validate-arguments" },
          { text: "Measure your model", link: "/guides/measure-your-model" },
          { text: "Guard third-party tools", link: "/guides/guard-third-party-tools" },
          { text: "Long catalogues", link: "/guides/long-catalogues" },
          { text: "Run the call loop", link: "/guides/call-loop" },
          { text: "Deploy the API", link: "/guides/deploy-the-api" },
          { text: "The dashboard", link: "/guides/dashboard" },
        ],
      },
      {
        text: "Reference",
        items: [
          { text: "Python SDK", link: "/reference/sdk" },
          { text: "Command line", link: "/reference/cli" },
          { text: "HTTP API", link: "/reference/http-api" },
        ],
      },
      {
        text: "Project",
        items: [
          { text: "FAQ", link: "/faq" },
          { text: "Contributing", link: "/contributing" },
          { text: "Changelog", link: "/changelog" },
          { text: "Citing ToolForm", link: "/citing" },
        ],
      },
    ],
    outline: { level: [2, 3], label: "On this page" },
    socialLinks: [{ icon: "github", link: "https://github.com/ctrl-gaurav/toolform" }],
    search: { provider: "local" },
    editLink: {
      pattern: "https://github.com/ctrl-gaurav/toolform/edit/main/docs/:path",
      text: "Edit this page on GitHub",
    },
    footer: { message: "Released under the Apache 2.0 License.", copyright: "© 2026 Gaurav Srivastava" },
  },
});
