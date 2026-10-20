"""The functional forms of the study's accuracy laws, which the advisor evaluates (the fitting code is
part of the study and is not shipped)."""

from .forms import *  # noqa: F401,F403

# Tool complexity of each tier on the [0, 1] scale the law forms use.
COMPLEXITY_BY_TIER = {1: 0.0, 2: 0.25, 3: 0.5, 4: 0.75, 5: 1.0}
