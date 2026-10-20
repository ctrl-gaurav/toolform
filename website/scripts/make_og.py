"""Draw public/og.png, the 1200 x 630 card link previews show.

The wordmark, the tagline and the study in numbers, on the site's dark
background. Run it with any Python that has matplotlib:

    python website/scripts/make_og.py

The fonts are whatever matplotlib finds (DejaVu Sans by default); the image is
committed, so the build does not need matplotlib.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

BG = "#06080C"
TEXT = "#E7ECF2"
MUTED = "#9AA6B5"
FAINT = "#7D8898"
ACCENT = "#4FE3C1"
BORDER = "#222B38"
OUT = Path(__file__).resolve().parents[1] / "public" / "og.png"

FACTS = [
    ("129", "schema formats"),
    ("31", "answer protocols"),
    ("112", "models"),
    ("66", "real tools"),
    ("69.18%", "measuring eight formats\non the target model"),
]


def main() -> None:
    fig = plt.figure(figsize=(12, 6.3), dpi=100)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, 1200)
    ax.set_ylim(630, 0)
    ax.axis("off")

    # the 32 px grid of the hero
    for x in range(0, 1201, 32):
        ax.plot([x, x], [0, 630], color=TEXT, alpha=0.035, lw=1)
    for y in range(0, 631, 32):
        ax.plot([0, 1200], [y, y], color=TEXT, alpha=0.035, lw=1)

    # the ladder mark, 24-unit grid scaled by 4
    s, x0, y0 = 4.0, 80, 96
    for i, (w, col) in enumerate([(5, TEXT), (10, TEXT), (15, TEXT), (20, ACCENT)]):
        y = 3 + 5 * i
        ax.add_patch(FancyBboxPatch((x0 + 2 * s, y0 + y * s), w * s, 3 * s,
                                    boxstyle=f"round,pad=0,rounding_size={1.5 * s}", fc=col, ec="none"))
    ax.text(x0 + 112, y0 + 58, "toolform", color=TEXT, fontsize=54, fontweight="bold",
            va="center", ha="left", family="DejaVu Sans")

    ax.text(80, 270, "Tool interfaces,", color=TEXT, fontsize=44, fontweight="bold", va="center")
    ax.text(80, 330, "chosen by measurement.", color=ACCENT, fontsize=44, fontweight="bold", va="center")
    ax.text(80, 392, "Choose, render, parse and guard the tool interface of an LLM agent.",
            color=MUTED, fontsize=19, va="center")

    ax.plot([80, 1120], [452, 452], color=BORDER, lw=1.2)
    cw = 1040 / len(FACTS)
    for i, (v, k) in enumerate(FACTS):
        x = 80 + i * cw
        ax.text(x, 500, v, color=ACCENT if i == len(FACTS) - 1 else TEXT, fontsize=30,
                family="DejaVu Sans Mono", va="center")
        ax.text(x, 552, k, color=FAINT, fontsize=14, va="top", linespacing=1.3)

    fig.savefig(OUT, facecolor=BG, dpi=100)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
