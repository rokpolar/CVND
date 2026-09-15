from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


OUTPUT = Path(__file__).resolve().parent / "final_results_figure.png"


def main() -> None:
    plt.rcParams.update({
        "font.size": 10,
        "axes.titlesize": 12,
        "axes.labelsize": 10,
        "figure.dpi": 180,
        "savefig.dpi": 300,
    })

    fig, (ax1, ax2) = plt.subplots(
        1, 2, figsize=(10.7, 4.8), gridspec_kw={"width_ratios": [1.2, 1]}
    )

    labels = [
        "Flood area\n30-day primary",
        "Flood area\n14-day sensitivity",
        "Urban share (+10 pp)\n30-day primary",
        "Urban share (+10 pp)\n14-day sensitivity",
    ]
    irr = np.array([1.006, 0.978, 1.152, 1.073])
    low = np.array([0.799, 0.745, 1.047, 0.987])
    high = np.array([1.267, 1.284, 1.267, 1.167])
    pvalues = [0.957, 0.870, 0.005, 0.094]
    y = np.arange(len(labels))[::-1]
    colors = ["#0f766e", "#94a3b8", "#0f766e", "#94a3b8"]

    for yi, value, lo, hi, color in zip(y, irr, low, high, colors):
        ax1.errorbar(
            value,
            yi,
            xerr=[[value - lo], [hi - value]],
            fmt="none",
            ecolor=color,
            elinewidth=2.2,
            capsize=4,
        )
    ax1.scatter(irr, y, c=colors, s=58, zorder=3, edgecolor="white", linewidth=0.7)
    ax1.axvline(1, color="#334155", linestyle="--", linewidth=1.2)
    ax1.set_yticks(y, labels)
    ax1.set_xlim(0.69, 1.34)
    ax1.set_xlabel("Incidence rate ratio (95% CI)")
    ax1.set_title("A. Adjusted associations (Model 2)", loc="left", weight="bold")
    ax1.grid(axis="x", color="#e2e8f0", linewidth=0.8)
    for yi, p in zip(y, pvalues):
        ax1.text(1.335, yi, f"p={p:.3f}", ha="right", va="center", fontsize=8.5)

    stages = ["Article observed", "Article complete", "Final analyzable"]
    primary = np.array([86.54, 1.16, 76.69])
    sensitivity = np.array([77.78, 1.48, 68.83])
    yy = np.arange(len(stages))[::-1]
    h = 0.32
    ax2.barh(yy + h / 2, primary, height=h, color="#0f766e", label="30-day primary")
    ax2.barh(yy - h / 2, sensitivity, height=h, color="#94a3b8", label="14-day sensitivity")
    ax2.set_yticks(yy, stages)
    ax2.set_xlim(0, 104)
    ax2.set_xlabel("Share of 1,553 registry rows (%)")
    ax2.set_title("B. News-data retention", loc="left", weight="bold")
    ax2.grid(axis="x", color="#e2e8f0", linewidth=0.8)
    ax2.legend(frameon=False, loc="center right")
    for positions, values in ((yy + h / 2, primary), (yy - h / 2, sensitivity)):
        for yi, value in zip(positions, values):
            ax2.text(value + 1.0, yi, f"{value:.1f}%", va="center", fontsize=8.5)

    for ax in (ax1, ax2):
        ax.set_axisbelow(True)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    fig.suptitle(
        "Flood extent, urbanization, and observed news coverage",
        fontsize=14,
        weight="bold",
        y=1.01,
    )
    fig.text(
        0.01,
        -0.02,
        "NB2 estimates with state-clustered SEs. Article counts are observed lower bounds.",
        fontsize=8.5,
        color="#475569",
    )
    fig.tight_layout()
    fig.savefig(OUTPUT, bbox_inches="tight", facecolor="white")


if __name__ == "__main__":
    main()
