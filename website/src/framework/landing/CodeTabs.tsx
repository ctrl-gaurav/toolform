import { useState } from "react";
import { CLI_EXAMPLE, HTTP_EXAMPLE, PY_EXAMPLE } from "../lib/snippets";
import { CodeBlock } from "../ui/CodeBlock";
import { Tabs } from "../ui/Tabs";

export function CodeTabs() {
  const [tab, setTab] = useState("python");
  return (
    <Tabs
      label="Code samples"
      value={tab}
      onChange={setTab}
      items={[
        { id: "python", label: "Python", panel: <CodeBlock code={PY_EXAMPLE} lang="python" title="recommend, render, parse" /> },
        { id: "cli", label: "CLI", panel: <CodeBlock code={CLI_EXAMPLE} lang="bash" title="toolform" /> },
        { id: "http", label: "HTTP", panel: <CodeBlock code={HTTP_EXAMPLE} lang="bash" title="toolform serve" /> },
      ]}
    />
  );
}
