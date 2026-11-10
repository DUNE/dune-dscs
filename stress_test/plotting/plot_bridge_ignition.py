from pathlib import Path
import re

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import numpy as np
import pandas as pd


# ---------- Settings ----------

BASE = Path(__file__).resolve().parents[1]
BRIDGE_DIR = BASE / "results" / "trial_with_ignition_script"
IGNITION_DIR = BASE / "results" / "timer_disabled_complete"
OUTPUT = BASE / "figures" / "combined_plots"
OUTPUT.mkdir(parents=True, exist_ok=True)
å
BRIDGE_COLOR = "#2563eb"
IGNITION_COLOR = "#d97706"

plt.rcParams.update({
    "font.size": 11,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "legend.frameon": False,
})


def save_plot(fig, name, pdf):
    fig.tight_layout()

    for extension in ("png", "pdf"):
        fig.savefig(
            OUTPUT / f"{name}.{extension}",
            dpi=300,
            bbox_inches="tight",
        )

    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {name}")


def statistics(values):
    values = pd.to_numeric(values, errors="coerce")
    values = values.replace([np.inf, -np.inf], np.nan).dropna()

    if values.empty:
        return {
            "samples": 0,
            "median": np.nan,
            "p05": np.nan,
            "p95": np.nan,
        }

    return {
        "samples": len(values),
        "median": values.median(),
        "p05": values.quantile(0.05),
        "p95": values.quantile(0.95),
    }


# ---------- Load bridge _1 files ----------

pattern = re.compile(r"bridge_N(\d+)_1\.csv")
rows = []

for file in BRIDGE_DIR.glob("bridge_N*_1.csv"):
    match = pattern.fullmatch(file.name)
    if match is None:
        continue

    try:
        data = pd.read_csv(file)
    except pd.errors.EmptyDataError:
        continue

    required = {"devices", "cpu_percent", "ram_mb"}
    if not required.issubset(data.columns):
        print(f"Skipping {file.name}: missing required columns")
        continue

    counts = pd.to_numeric(data["devices"], errors="coerce")
    unique_counts = counts.dropna().unique()

    if (
        counts.isna().any()
        or len(unique_counts) != 1
        or not np.isfinite(unique_counts[0])
        or unique_counts[0] < 0
        or unique_counts[0] != int(unique_counts[0])
    ):
        raise ValueError(f"{file.name}: invalid device count")

    n = int(unique_counts[0])

    if n != int(match.group(1)):
        print(f"WARNING: {file.name} contains N={n}; using recorded N")

    for metric, column in [
        ("cpu", "cpu_percent"),
        ("ram", "ram_mb"),
    ]:
        rows.append({
            "component": "Bridge",
            "N": n,
            "metric": metric,
            "source": file.name,
            **statistics(data[column]),
        })


# ---------- Load Ignition resources ----------

ignition = pd.read_csv(IGNITION_DIR / "ignition_resources.csv")

for column in ("N", "cpu_percent", "rss_mb"):
    ignition[column] = pd.to_numeric(
        ignition[column], errors="coerce"
    )

ignition["time_utc"] = pd.to_datetime(
    ignition["time_utc"],
    utc=True,
    errors="coerce",
    format="ISO8601",
)

ignition = ignition.replace([np.inf, -np.inf], np.nan)
ignition = ignition.dropna(
    subset=["N", "time_utc", "cpu_percent", "rss_mb"]
)

# Use the latest logged Ignition attempt per N when diagnostics exists.
diagnostic_file = IGNITION_DIR / "ignition_tag_diagnostics.csv"
diagnostics = None

if diagnostic_file.exists():
    diagnostics = pd.read_csv(diagnostic_file)

    diagnostics["N"] = pd.to_numeric(
        diagnostics["N"], errors="coerce"
    )
    diagnostics["time_utc"] = pd.to_datetime(
        diagnostics["time_utc"],
        utc=True,
        errors="coerce",
        format="ISO8601",
    )
    diagnostics = diagnostics.dropna(
        subset=["N", "time_utc", "run_id"]
    ).sort_values("time_utc")

else:
    print(
        "WARNING: no tag diagnostics file. "
        "Ignition samples for repeated N values will be pooled."
    )

for n, group in ignition.groupby("N"):
    if n < 0 or n != int(n):
        raise ValueError(f"Invalid Ignition N: {n}")

    n = int(n)
    window = "All resource samples for N"

    if diagnostics is not None:
        tag_data = diagnostics[diagnostics["N"] == n]

        if tag_data.empty:
            print(f"N={n}: no matching Ignition run; skipping")
            continue

        latest_run = tag_data.iloc[-1]["run_id"]
        tag_data = tag_data[tag_data["run_id"] == latest_run]

        start = tag_data["time_utc"].min()
        end = tag_data["time_utc"].max()

        group = group[
            group["time_utc"].between(start, end)
        ]
        window = f"Latest tag-run window: {latest_run}"

    if group.empty:
        continue

    for metric, column in [
        ("cpu", "cpu_percent"),
        ("ram", "rss_mb"),
    ]:
        rows.append({
            "component": "Ignition",
            "N": n,
            "metric": metric,
            "source": window,
            **statistics(group[column]),
        })


# ---------- Keep device counts available for both ----------

summary = pd.DataFrame(rows)

if summary.empty:
    raise SystemExit("No measurements found.")

summary = summary[summary["samples"] > 0].copy()

duplicates = summary.duplicated(
    ["component", "N", "metric"], keep=False
)
if duplicates.any():
    raise ValueError(
        "Multiple bridge files map to the same N. "
        "Check their devices columns."
    )

bridge_ns = set(
    summary.loc[summary["component"] == "Bridge", "N"]
)
ignition_ns = set(
    summary.loc[summary["component"] == "Ignition", "N"]
)
common_ns = sorted(bridge_ns & ignition_ns)

if not common_ns:
    raise SystemExit("No common N values for bridge and Ignition.")

summary = summary[summary["N"].isin(common_ns)]
summary = summary.sort_values(["metric", "component", "N"])

summary.to_csv(
    OUTPUT / "bridge_ignition_summary.csv",
    index=False,
)

print("Comparing N:", common_ns)


# ---------- Draw comparisons ----------

def draw_comparison(ax, metric, title, ylabel):
    for component, color in [
        ("Bridge", BRIDGE_COLOR),
        ("Ignition", IGNITION_COLOR),
    ]:
        selected = summary[
            (summary["component"] == component)
            & (summary["metric"] == metric)
        ].sort_values("N")

        ax.fill_between(
            selected["N"].to_numpy(),
            selected["p05"].to_numpy(),
            selected["p95"].to_numpy(),
            color=color,
            alpha=0.14,
        )

        ax.plot(
            selected["N"],
            selected["median"],
            color=color,
            marker="o",
            markersize=4,
            linewidth=1.8,
            label=component,
        )

    ax.set(
        title=title,
        xlabel="Number of devices, N",
        ylabel=ylabel,
    )
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    ax.grid(axis="y", alpha=0.2)
    ax.set_axisbelow(True)
    ax.legend()


with PdfPages(OUTPUT / "bridge_ignition_comparison.pdf") as pdf:

    for metric, title, ylabel in [
        ("cpu", "Bridge and Ignition CPU usage", "Process CPU usage (%)"),
        ("ram", "Bridge and Ignition memory", "Resident memory (MB)"),
    ]:
        fig, ax = plt.subplots(figsize=(9, 5))
        draw_comparison(ax, metric, title, ylabel)

        save_plot(fig, f"bridge_ignition_{metric}_vs_N", pdf)

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))

    draw_comparison(
        axes[0], "cpu", "CPU usage", "Process CPU usage (%)"
    )
    draw_comparison(
        axes[1], "ram", "Resident memory", "Resident memory (MB)"
    )

    save_plot(fig, "bridge_ignition_resources_vs_N", pdf)

print(f"\nPDF: {OUTPUT / 'bridge_ignition_comparison.pdf'}")