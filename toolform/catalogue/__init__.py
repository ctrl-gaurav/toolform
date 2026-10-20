"""Long tool catalogues: retrieval, names-first two-stage disclosure, budgets and plans.

The study measured each: going from 1 to 256 tools cost 41.01%; on a 128-tool
panel the top 8 by BM25 reached 31.19% against 12.70% for the whole panel;
names and descriptions first gained 26.72% over one shot at 256 tools.
"""

from .budget import BudgetResult, fit_to_budget
from .disclosure import SELECTION_ASK, TwoStage, TwoStageResult
from .plan import CataloguePlan, plan_catalogue
from .retrieve import Retrieval, retrieve

__all__ = [
    "BudgetResult",
    "CataloguePlan",
    "Retrieval",
    "SELECTION_ASK",
    "TwoStage",
    "TwoStageResult",
    "fit_to_budget",
    "plan_catalogue",
    "retrieve",
]
