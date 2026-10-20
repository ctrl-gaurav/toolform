"""A long catalogue: 93 generated tools across 24 domains.

    python examples/long_catalogue.py

It plans how to show them (one shot, retrieval, or names first), ranks them
against a request with the study's BM25, and builds the stage-one prompt of
names-first disclosure. In the study, going from 1 to 256 tools cost 41.01%
of accuracy, and showing names and descriptions first gained 26.72% over one
shot at 256 tools.
"""

from __future__ import annotations

from toolform.catalogue import TwoStage, fit_to_budget, plan_catalogue, retrieve
from toolform.sdk import generated_toolset

REQUEST = "Convert 250 US dollars to euros at today's exchange rate."


def main() -> None:
    tools = generated_toolset()
    print(f"{len(tools)} generated tools")

    for n, window in ((8, None), (40, None), (16, 4_096), (93, 32_768)):
        subset = tools.subset(tools.names()[:n])
        plan = plan_catalogue(subset, format_id="xml_schema", context_tokens=window, query=REQUEST)
        label = f"{n} tools" + (f", {window:,}-token window" if window else "")
        print(f"\n{label}: {plan.strategy} (the block is about {plan.schema_tokens:,} tokens)")
        print(f"  {plan.reason}")

    ranked = retrieve(tools, REQUEST, k=8)
    print(f"\nBM25 top 8 for {REQUEST!r}:")
    for name, score in ranked.ranked[:8]:
        print(f"  {score:6.3f}  {name}")

    stage = TwoStage(tools, include_descriptions=True)
    messages = stage.selection_messages(REQUEST)
    print(f"\nstage-one prompt: {len(messages)} messages, {sum(len(m['content']) for m in messages):,} characters")
    print("  it ends with:", messages[-1]["content"].splitlines()[-1])

    fitted = fit_to_budget(tools, "xml_schema", 4_000, query=REQUEST)
    print(
        f"\nfit to 4,000 tokens: {fitted.tokens_before:,} -> {fitted.tokens_after:,} tokens, "
        f"{len(fitted.kept)} tools kept, fits={fitted.fits}"
    )


if __name__ == "__main__":
    main()
