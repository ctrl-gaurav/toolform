"""The advisor: recommend a format and protocol from the study's evidence, or measure them.

``recommend`` reads the shipped evidence tables and needs no model.
``ab_test`` runs the study's "measure eight" procedure on your own endpoint,
which beat every fixed rule in the study.
"""

from .evidence import Evidence, EvidenceRow, load_evidence
from .measure import Example, FormatScore, MeasureReport, ab_test, load_examples
from .recommend import Advisor, Alternative, CatalogueAdvice, GuardAdvice, Recommendation, recommend
from .situation import ModelResolution, Situation, resolve_model
from .surface import Surface

__all__ = [
    "Evidence",
    "EvidenceRow",
    "load_evidence",
    "Situation",
    "ModelResolution",
    "resolve_model",
    "Recommendation",
    "Alternative",
    "CatalogueAdvice",
    "GuardAdvice",
    "Advisor",
    "recommend",
    "Example",
    "FormatScore",
    "MeasureReport",
    "ab_test",
    "load_examples",
    "Surface",
]
