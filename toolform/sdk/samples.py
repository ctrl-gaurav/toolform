"""Sample tools: the paper's worked example and the study's 66 real tools."""

from __future__ import annotations

from ..ir import ParamIR, ToolIR, TypeIR, TypeKind
from .toolset import Toolset


def sample_tool() -> ToolIR:
    """``legal_draft_v3``, the tool every format is shown with in the paper's appendix.

    It has three required scalars with constraints, an optional boolean with a
    default, and an optional object holding a string and an enum: tier 3 of
    the generator.
    """
    return ToolIR(
        name="legal_draft_v3",
        description="Draft a new contract. Works on the contracts and clauses data set.",
        params=(
            ParamIR(name="counterparty", type=TypeIR(kind=TypeKind.STRING), description="Other party.", required=True),
            ParamIR(
                name="value",
                type=TypeIR.number(minimum=0),
                description="Contract value. Value must be at least 0.",
                required=True,
            ),
            ParamIR(
                name="term_months",
                type=TypeIR.integer(minimum=1, maximum=600),
                description="Length of the term.",
                required=True,
            ),
            ParamIR(
                name="auto_renew",
                type=TypeIR.boolean(),
                description="Whether it renews automatically.",
                required=False,
                default=False,
            ),
            ParamIR(
                name="contract_details",
                type=TypeIR.object_of(
                    [
                        ParamIR(
                            name="contract_id",
                            type=TypeIR(kind=TypeKind.STRING),
                            description="Contract number.",
                            required=False,
                        ),
                        ParamIR(
                            name="status",
                            type=TypeIR.enum_of(["draft", "review", "signed", "expired"]),
                            description="Where it stands.",
                            required=False,
                        ),
                    ]
                ),
                description="Details of the contract.",
                required=False,
            ),
        ),
        returns=TypeIR(kind=TypeKind.OBJECT),
        returns_description="the contract id",
        domain="legal",
        category="legal",
        origin="sample",
    )


def sample_toolset() -> Toolset:
    """A one-tool Toolset holding :func:`sample_tool`."""
    return Toolset.from_tools([sample_tool()], name="sample", source="sample")


__all__ = ["generated_toolset", "sample_tool", "sample_toolset"]


def generated_toolset(tier: int = 2, *, max_variants: int = 1, limit: int | None = None) -> Toolset:
    """A large catalogue of generated tools across the generator's 24 domains (weather, calendar,
    finance, ...), for trying long-catalogue features such as disclosure, retrieval and budgets.

    ``tier`` (1 to 5) sets the parameter complexity and ``max_variants`` how many interface variants of
    each operation are included; ``limit`` keeps only the first ``limit`` tools."""
    from ..generator.universe import all_base_tools

    tools = all_base_tools(tier, max_variants=max_variants)
    if limit is not None:
        tools = tools[:limit]
    return Toolset.from_tools(tools, name=f"generated_t{tier}", source="generated")
