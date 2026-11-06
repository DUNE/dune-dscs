from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import numpy as np
import pandas as pd


# ---------- Settings ----------

BASE = Path(__file__).resolve().parent
OUTPUT = BASE / "timer_comparison_plots"
OUTPUT.mkdir(exist_ok=True)

N = 900
STATES = ("enabled", "disabled")

COLORS = {
    "enabled": "#d97706",
    "disabled": "#2563eb",
}

LABELS = {
    "enabled": "Timer enabled",
    "disabled": "Timer disabled",
}

plt.rcParams.update({
    "font.size": 11,
    "axes.titlesize": 12,
    "axes.labelsize": 11,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "legend.frameon": False,
    "figure.facecolor": "white",
    "savefig.facecolor": "white",
})


# ---------- Helpers ----------

def save_plot(fig, name, pdf, note=None):
    if note:
        fig.text(
            0.5, 0.015,
            note,
            ha="center",
            fontsize=9,
            color="#555555",
        )
        fig.tight_layout(rect=(0, 0.07, 1, 0.94))
    else:
        fig.tight_layout(rect=(0, 0, 1, 0.94))

    for extension in ("png", "pdf"):
        fig.savefig(
            OUTPUT / f"{name}.{extension}",
            dpi=300,
            bbox_inches="tight",
        )

    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {name}")


def load_data(filename, numeric_columns):
    path = BASE / filename
    data = pd.read_csv(path)

    required = {"time_utc"} | set(numeric_columns)
    missing = required - set(data.columns)

    if missing:
        raise ValueError(
            f"{filename}: missing columns {sorted(missing)}"
        )

    data["time_utc"] = pd.to_datetime(
        data["time_utc"],
        utc=True,
        errors="coerce",
        format="ISO8601",
    )

    for column in numeric_columns:
        data[column] = pd.to_numeric(
            data[column], errors="coerce"
        )

    data = data.replace([np.inf, -np.inf], np.nan)

    valid = data[list(required)].notna().all(axis=1)

    if (~valid).any():
        print(
            f"WARNING: {filename}: "
            f"excluded {(~valid).sum()} invalid rows"
        )

    data = data.loc[valid].sort_values("time_utc").copy()

    if data.empty:
        raise ValueError(f"{filename}: no usable measurements")

    return data


# ---------- Load and align the two runs ----------

datasets = {}
summary_rows = []

for state in STATES:
    resources = load_data(
        f"ignition_N{N}_timer_{state}.csv",
        ["N", "cpu_percent", "rss_mb"],
    )

    bridge = load_data(
        f"bridge_N{N}_timer_{state}.csv",
        ["devices", "cycle_s"],
    )

    if not resources["N"].eq(N).all():
        raise ValueError(
            f"Ignition timer-{state} file contains another N"
        )

    if not bridge["devices"].eq(N).all():
        raise ValueError(
            f"Bridge timer-{state} file contains another N"
        )

    if not bridge["cycle_s"].gt(0).all():
        raise ValueError("Bridge cycle durations must be positive")

    # The timestamp marks the end of a bridge cycle.
    # Subtract its duration to recover the first measured cycle's start.
    first = bridge.iloc[0]

    start = (
        first["time_utc"]
        - pd.to_timedelta(first["cycle_s"], unit="s")
    )
    end = bridge.iloc[-1]["time_utc"]

    # Exclude resource samples before/after measured bridge cycles.
    resources = resources[
        resources["time_utc"].between(start, end)
    ].copy()

    if resources.empty:
        raise ValueError(
            f"No matching Ignition samples for timer {state}"
        )

    resources["elapsed_min"] = (
        resources["time_utc"] - start
    ).dt.total_seconds() / 60

    datasets[state] = resources

    cpu = resources["cpu_percent"]
    ram = resources["rss_mb"]

    summary_rows.append({
        "state": state,
        "N": N,
        "samples": len(resources),
        "start_utc": start.isoformat(),
        "end_utc": end.isoformat(),
        "mean_cpu": cpu.mean(),
        "median_cpu": cpu.median(),
        "p95_cpu": cpu.quantile(0.95),
        "max_cpu": cpu.max(),
        "above_50_percent": 100 * cpu.gt(50).mean(),
        "median_ram": ram.median(),
        "bridge_cycle_median_s": bridge["cycle_s"].median(),
    })

    print(
        f"Timer {state}: {len(resources)} resource samples; "
        f"{len(bridge)} measured bridge cycles"
    )

summary = pd.DataFrame(summary_rows).set_index("state")
summary.to_csv(OUTPUT / "timer_comparison_summary.csv")

print("\nSummary:")
print(
    summary[
        [
            "samples",
            "mean_cpu",
            "median_cpu",
            "p95_cpu",
            "max_cpu",
            "above_50_percent",
            "median_ram",
            "bridge_cycle_median_s",
        ]
    ].round(3).to_string()
)

maximum_cpu = max(
    data["cpu_percent"].max()
    for data in datasets.values()
)

maximum_time = max(
    data["elapsed_min"].max()
    for data in datasets.values()
)

cpu_limit = max(
    10,
    np.ceil(maximum_cpu / 10) * 10 + 5,
)


# ---------- Generate figures and combined PDF ----------

pdf_path = OUTPUT / f"timer_comparison_N{N}.pdf"

with PdfPages(pdf_path) as pdf:

    # ========================================================
    # 1. CPU over time, using identical main axes
    # ========================================================

    fig, axes = plt.subplots(
        2, 1,
        figsize=(10, 6.5),
        sharex=True,
        sharey=True,
    )

    for ax, state in zip(axes, STATES):
        data = datasets[state]

        ax.plot(
            data["elapsed_min"],
            data["cpu_percent"],
            color=COLORS[state],
            linewidth=0.9,
        )

        ax.set_title(
            LABELS[state],
            loc="left",
            fontweight="bold",
        )

        ax.set_ylabel("Process CPU (%)")
        ax.set_ylim(0, cpu_limit)
        ax.set_xlim(0, maximum_time)
        ax.grid(axis="y", alpha=0.18)
        ax.set_axisbelow(True)

        ax.text(
            0.98, 0.86,
            (
                f"Mean {summary.loc[state, 'mean_cpu']:.2f}%"
                f"  |  P95 {summary.loc[state, 'p95_cpu']:.2f}%"
            ),
            transform=ax.transAxes,
            ha="right",
            fontsize=10,
            bbox={
                "facecolor": "white",
                "edgecolor": "none",
                "alpha": 0.9,
            },
        )

    # Explicitly labelled zoom for small timer-disabled variations.
    disabled = datasets["disabled"]
    inset = axes[1].inset_axes([0.56, 0.30, 0.40, 0.44])

    inset.plot(
        disabled["elapsed_min"],
        disabled["cpu_percent"],
        color=COLORS["disabled"],
        linewidth=0.7,
    )

    inset.set_xlim(0, maximum_time)
    inset.set_ylim(
        0,
        max(1, disabled["cpu_percent"].max() * 1.15),
    )
    inset.set_title("Timer disabled — zoom", fontsize=9)
    inset.tick_params(labelsize=8)
    inset.grid(alpha=0.15)

    axes[-1].set_xlabel(
        "Time since measured-window start (minutes)"
    )

    fig.suptitle(
        f"Diagnostic timer overhead on Ignition\n"
        f"{N} emulators · {3 * N:,} configured test tags",
        fontsize=15,
    )

    save_plot(
        fig,
        f"cpu_over_time_N{N}",
        pdf,
        note="Main panels use identical scales. CPU 100% = one logical CPU.",
    )

    # ========================================================
    # 2. Mean and P95 CPU
    # ========================================================

    fig, axes = plt.subplots(1, 2, figsize=(9, 4.8))

    for ax, metric, title in [
        (axes[0], "mean_cpu", "Mean CPU usage"),
        (axes[1], "p95_cpu", "P95 CPU usage"),
    ]:
        values = [
            float(summary.loc[state, metric])
            for state in STATES
        ]

        bars = ax.bar(
            [0, 1],
            values,
            width=0.5,
            color=[COLORS[state] for state in STATES],
        )

        ax.bar_label(
            bars,
            labels=[f"{value:.2f}%" for value in values],
            padding=6,
            fontsize=12,
            fontweight="bold",
        )

        ax.set_xticks([0, 1])
        ax.set_xticklabels(["Timer on", "Timer off"])
        ax.set_title(title)
        ax.set_ylabel("Process CPU (%)")
        ax.set_ylim(0, max(values) * 1.35 + 0.2)
        ax.grid(axis="y", alpha=0.18)
        ax.set_axisbelow(True)

    mean_on = summary.loc["enabled", "mean_cpu"]
    mean_off = summary.loc["disabled", "mean_cpu"]

    if mean_on > 0:
        reduction = 100 * (1 - mean_off / mean_on)
        title = (
            f"Mean CPU reduction with timer disabled: "
            f"{reduction:.1f}%"
        )
    else:
        title = "Ignition CPU comparison"

    fig.suptitle(title, fontsize=14)

    save_plot(
        fig,
        f"cpu_summary_N{N}",
        pdf,
        note="Each panel starts at zero; the two panels use different vertical scales.",
    )

    # ========================================================
    # 3. CPU distribution: zoom and full observed range
    # ========================================================

    fig, axes = plt.subplots(
        1, 2,
        figsize=(11, 4.8),
        sharey=True,
    )

    for state in STATES:
        cpu = np.sort(
            datasets[state]["cpu_percent"].to_numpy()
        )

        x = np.unique(np.r_[0.0, cpu])
        cumulative = (
            100
            * np.searchsorted(cpu, x, side="right")
            / len(cpu)
        )

        for ax in axes:
            ax.step(
                x,
                cumulative,
                where="post",
                color=COLORS[state],
                linewidth=2,
                label=LABELS[state],
            )

    axes[0].set_xlim(0, 5)
    axes[0].set_title("Low-CPU region: 0–5%")
    axes[0].set_ylabel(
        "Samples at or below CPU level (%)"
    )

    axes[1].set_xlim(0, cpu_limit)
    axes[1].set_title("Full observed range")
    axes[1].legend(loc="lower right", fontsize=10)

    for ax in axes:
        ax.set_xlabel("Process CPU usage (%)")
        ax.set_ylim(0, 102)
        ax.grid(alpha=0.18)

    fig.suptitle(
        f"Ignition CPU distribution | N = {N}",
        fontsize=15,
    )

    save_plot(fig, f"cpu_distribution_N{N}", pdf)

    # ========================================================
    # 4. Resident memory over time
    # ========================================================

    fig, ax = plt.subplots(figsize=(10, 4.8))

    all_ram = []

    for state in STATES:
        data = datasets[state]
        all_ram.extend(data["rss_mb"].to_numpy())

        median_ram = summary.loc[state, "median_ram"]

        ax.plot(
            data["elapsed_min"],
            data["rss_mb"],
            color=COLORS[state],
            linewidth=1.4,
            label=(
                f"{LABELS[state]} "
                f"(median {median_ram:.2f} MB)"
            ),
        )

    minimum_ram = min(all_ram)
    maximum_ram = max(all_ram)
    padding = max(
        0.5,
        (maximum_ram - minimum_ram) * 0.15,
    )

    ax.set_ylim(
        minimum_ram - padding,
        maximum_ram + padding,
    )
    ax.set_xlim(0, maximum_time)

    ax.ticklabel_format(
        axis="y",
        style="plain",
        useOffset=False,
    )

    ax.set_title(f"Ignition resident memory | N = {N}")
    ax.set_xlabel(
        "Time since measured-window start (minutes)"
    )
    ax.set_ylabel("Resident memory (MB)")
    ax.grid(axis="y", alpha=0.18)
    ax.legend()

    save_plot(
        fig,
        f"memory_comparison_N{N}",
        pdf,
        note="Vertical axis is zoomed. RSS is process memory, not JVM heap usage.",
    )

print(f"\nCombined PDF: {pdf_path}")
print(f"Individual figures and summary: {OUTPUT}")