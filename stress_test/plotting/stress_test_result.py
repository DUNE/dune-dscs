from pathlib import Path
import re
import textwrap

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import numpy as np
import pandas as pd

from matplotlib.ticker import MaxNLocator


# ---------- Settings ----------

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "results" / "trial_with_ignition_script"
PLOT_DIR = ROOT / "figures" / "plots"
PLOT_DIR.mkdir(parents=True, exist_ok=True)

WARMUP_CYCLES = 0
EXTRA_THRESHOLD_S = 0.100
POLL_SLEEP_S = 1.0  # Must match the bridge's intentional sleep.

BLUE = "#2563eb"
ORANGE = "#d97706"
GREEN = "#059669"
PURPLE = "#9333ea"

plt.rcParams.update({
    "font.size": 11,
    "axes.titlesize": 13,
    "axes.labelsize": 11,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "legend.frameon": False,
    "figure.facecolor": "white",
    "savefig.facecolor": "white",
})


# ---------- Plot helpers ----------

def save_plot(fig, name, pdf, note=None):
    if note:
        fig.text(
            0.5, 0.015,
            textwrap.fill(note, width=105),
            ha="center",
            va="bottom",
            fontsize=9,
            color="#555555",
        )
        fig.tight_layout(rect=(0, 0.11, 1, 1))
    else:
        fig.tight_layout()

    for extension in ("png", "pdf"):
        fig.savefig(
            PLOT_DIR / f"{name}.{extension}",
            dpi=300,
            bbox_inches="tight",
        )

    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {name}")


def style_axis(ax, versus_n=False):
    ax.grid(axis="y", alpha=0.2)
    ax.set_axisbelow(True)

    if versus_n:
        ax.set_xlabel("Number of configured devices, N")
        ax.set_xlim(left=0)


def add_line(ax, x, y, label, color, linestyle="-"):
    values = np.asarray(y, dtype=float)

    if not np.isfinite(values).any():
        return

    ax.plot(
        x, values,
        color=color,
        marker="o",
        markersize=4,
        linewidth=1.7,
        linestyle=linestyle,
        label=label,
    )


def add_legend(ax):
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(fontsize=9)


def median_band(ax, summary, metric):
    selected = summary[
        summary["metric"] == metric
    ].sort_values("N")

    if selected.empty:
        ax.text(
            0.5, 0.5, "Measurement unavailable",
            ha="center", transform=ax.transAxes,
        )
        return selected

    ax.fill_between(
        selected["N"].to_numpy(),
        selected["p05"].to_numpy(),
        selected["p95"].to_numpy(),
        color=BLUE,
        alpha=0.16,
        label="P5–P95 across cycles",
    )

    add_line(
        ax,
        selected["N"],
        selected["median"],
        "Median across cycles",
        BLUE,
    )

    return selected


# ---------- Load only bridge_N<number>_1.csv ----------

pattern = re.compile(r"bridge_N(\d+)_1\.csv")
datasets = []

for file in DATA_DIR.glob("bridge_N*_1.csv"):
    match = pattern.fullmatch(file.name)
    if match is None:
        continue

    try:
        data = pd.read_csv(file)
    except pd.errors.EmptyDataError:
        print(f"Skipping empty file: {file.name}")
        continue

    required = {"cycle", "cycle_s", "devices"}
    missing = required - set(data.columns)

    if missing:
        print(f"Skipping {file.name}: missing {sorted(missing)}")
        continue

    for column in data.columns:
        if column not in {"time_utc", "slowest_host"}:
            data[column] = pd.to_numeric(
                data[column], errors="coerce"
            )

    data = data.replace([np.inf, -np.inf], np.nan)

    valid = (
        data["cycle"].notna()
        & data["cycle_s"].notna()
        & (data["cycle_s"] > 0)
    )

    if (~valid).any():
        print(f"{file.name}: dropping {(~valid).sum()} invalid rows")

    data = data.loc[valid].copy()
    data = data[data["cycle"] > WARMUP_CYCLES]
    data = data.sort_values("cycle")

    if data.empty:
        print(f"No usable cycles: {file.name}")
        continue

    counts = data["devices"].dropna().unique()

    if (
        data["devices"].isna().any()
        or len(counts) != 1
        or counts[0] < 0
        or counts[0] != int(counts[0])
    ):
        raise ValueError(f"{file.name}: invalid device counts")

    n = int(counts[0])

    if n != int(match.group(1)):
        print(
            f"WARNING: {file.name} records N={n}. "
            "Using the recorded count."
        )

    if data["cycle"].duplicated().any():
        raise ValueError(f"{file.name}: duplicate cycle numbers")

    datasets.append({
        "file": file,
        "N": n,
        "data": data,
    })

datasets.sort(key=lambda item: item["N"])

if not datasets:
    raise SystemExit("No usable bridge_N<number>_1.csv files found.")

counts = [item["N"] for item in datasets]
if len(counts) != len(set(counts)):
    raise ValueError("Multiple selected files have the same N.")

print("\nFiles used:")
for item in datasets:
    print(
        f"  {item['file'].name}: "
        f"N={item['N']}, {len(item['data'])} cycles"
    )


# ---------- Summarise per-cycle measurements ----------

METRICS = {
    "cycle_s": (
        "Polling-cycle duration", "Cycle duration (s)"
    ),
    "cpu_percent": (
        "Bridge CPU usage", "Process CPU usage (%)"
    ),
    "ram_mb": (
        "Bridge resident memory", "Resident memory (MB)"
    ),
    "acquisitions_per_s": (
        "Successful acquisition rate per cycle",
        "Acquisitions/s — all devices"
    ),
    "node_writes_per_s": (
        "Successful variable-write rate per cycle",
        "Writes/s — all variables"
    ),
    "failure_percent": (
        "Request failure percentage per cycle", "Failed requests (%)"
    ),
    "timeouts": (
        "Receive timeouts per cycle", "Timeout count"
    ),
    "send_errors": (
        "Send errors per cycle", "Send error count"
    ),
    "other_errors": (
        "Other request errors per cycle", "Error count"
    ),
    "mean_request_ms": (
        "Mean request latency per cycle", "Request duration (ms)"
    ),
    "request_median_ms": (
        "Median request latency per cycle", "Request duration (ms)"
    ),
    "request_p95_ms": (
        "Request latency P95 per cycle", "Request duration (ms)"
    ),
    "request_p99_ms": (
        "Request latency P99 per cycle", "Request duration (ms)"
    ),
    "parse_total_ms": (
        "Total response-parsing time per cycle", "Parsing duration (ms)"
    ),
    "update_total_ms": (
        "Total OPC UA update time per cycle", "Update duration (ms)"
    ),
    "zmq_tx_payload_kB_s": (
        "Transmitted ZMQ payload throughput", "Payload (kB/s)"
    ),
    "zmq_rx_payload_kB_s": (
        "Received ZMQ payload throughput", "Payload (kB/s)"
    ),
}

summary_rows = []

for item in datasets:
    for metric in METRICS:
        if metric not in item["data"]:
            continue

        values = item["data"][metric].dropna()
        if values.empty:
            continue

        summary_rows.append({
            "file": item["file"].name,
            "N": item["N"],
            "metric": metric,
            "samples": len(values),
            "mean": values.mean(),
            "std": values.std(),
            "minimum": values.min(),
            "p05": values.quantile(0.05),
            "median": values.median(),
            "p95": values.quantile(0.95),
            "p99": values.quantile(0.99),
            "maximum": values.max(),
        })

summary = pd.DataFrame(summary_rows)
summary.to_csv(PLOT_DIR / "bridge_summary_1.csv", index=False)


# ---------- Whole-run rates ----------

def total_rate(data, column):
    if column not in data:
        return np.nan

    valid = data[column].notna()
    seconds = data.loc[valid, "cycle_s"].sum()

    if seconds <= 0:
        return np.nan

    return data.loc[valid, column].sum() / seconds


def weighted_throughput(data, column):
    if column not in data:
        return np.nan

    valid = data[column].notna()
    seconds = data.loc[valid, "cycle_s"].sum()

    if seconds <= 0:
        return np.nan

    return (
        data.loc[valid, column]
        * data.loc[valid, "cycle_s"]
    ).sum() / seconds


failure_columns = ["timeouts", "send_errors", "other_errors"]
run_rows = []

for item in datasets:
    data = item["data"]

    row = {
        "file": item["file"].name,
        "N": item["N"],
        "cycles": len(data),
        "measured_cycle_time_s": data["cycle_s"].sum(),
        "acquisitions_per_s": total_rate(data, "successes"),
        "node_writes_per_s": total_rate(data, "node_writes"),
        "tx_payload_kB_s": weighted_throughput(
            data, "zmq_tx_payload_kB_s"
        ),
        "rx_payload_kB_s": weighted_throughput(
            data, "zmq_rx_payload_kB_s"
        ),
        "failure_percent": np.nan,
        "failure_cycles_used": 0,
    }

    for column in failure_columns:
        row[f"{column}_percent"] = np.nan

    needed = ["attempts"] + failure_columns

    if set(needed).issubset(data.columns):
        valid = data[needed].notna().all(axis=1)
        checked = data.loc[valid]
        attempts = checked["attempts"].sum()
        row["failure_cycles_used"] = len(checked)

        if attempts > 0:
            for column in failure_columns:
                row[f"{column}_percent"] = (
                    100 * checked[column].sum() / attempts
                )

            row["failure_percent"] = sum(
                row[f"{column}_percent"]
                for column in failure_columns
            )

    run_rows.append(row)

runs = pd.DataFrame(run_rows).sort_values("N")
runs.to_csv(PLOT_DIR / "bridge_run_totals_1.csv", index=False)


# ============================================================
# PDF 1: MAIN RESULTS
# ============================================================

with PdfPages(PLOT_DIR / "all_bridge_plots.pdf") as pdf:

    # Individual cycle-duration plots.
    for item in datasets:
        data = item["data"]
        fig, ax = plt.subplots(figsize=(9, 4.5))

        ax.plot(
            data["cycle"], data["cycle_s"],
            color=BLUE, linewidth=1,
            marker=".", markersize=3,
            label="Measured cycle duration",
        )

        median = data["cycle_s"].median()
        ax.axhline(
            median, color=ORANGE,
            linestyle="--",
            label=f"Median: {median:.3f} s",
        )

        ax.set(
            title=f"Bridge cycle duration | N = {item['N']}",
            xlabel="Polling cycle",
            ylabel="Cycle duration (s)",
        )
        style_axis(ax)
        add_legend(ax)

        save_plot(
            fig, f"{item['file'].stem}_cycle_time", pdf
        )

    # Each metric versus N.
    for metric, (title, ylabel) in METRICS.items():
        if metric not in set(summary["metric"]):
            continue

        fig, ax = plt.subplots(figsize=(9, 5))
        selected = median_band(ax, summary, metric)

        if metric == "cycle_s":
            add_line(
                ax, selected["N"], selected["p99"],
                "P99 across cycles", ORANGE, "--",
            )

        ax.set_title(title)
        ax.set_ylabel(ylabel)
        style_axis(ax, versus_n=True)
        add_legend(ax)

        note = "Bands show variation across cycles, not confidence intervals."
        if metric == "cpu_percent":
            note += " 100% CPU = one logical CPU."
        elif metric in {
            "request_median_ms", "request_p95_ms", "request_p99_ms"
        }:
            note += " These are per-cycle request statistics."

        save_plot(fig, f"{metric}_vs_N_1", pdf, note)

    # Combined CPU and RAM.
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))

    for ax, metric, title, ylabel in [
        (axes[0], "cpu_percent", "Bridge CPU", "Process CPU (%)"),
        (axes[1], "ram_mb", "Bridge memory", "Resident memory (MB)"),
    ]:
        median_band(ax, summary, metric)
        ax.set_title(title)
        ax.set_ylabel(ylabel)
        style_axis(ax, versus_n=True)
        add_legend(ax)

    save_plot(
        fig, "resources_vs_N_1", pdf,
        "P5–P95 describes cycles. 100% CPU = one logical CPU.",
    )

    # Combined latency.
    fig, ax = plt.subplots(figsize=(9, 5))

    for metric, label, color in [
        ("request_median_ms", "Cycle request median", BLUE),
        ("request_p95_ms", "Cycle request P95", GREEN),
        ("request_p99_ms", "Cycle request P99", ORANGE),
    ]:
        selected = summary[summary["metric"] == metric]
        add_line(
            ax, selected["N"], selected["median"], label, color
        )

    ax.set_title("ZMQ request latency versus device count")
    ax.set_ylabel("Request–response duration (ms)")
    style_axis(ax, versus_n=True)
    add_legend(ax)

    save_plot(
        fig, "request_latency_combined_vs_N_1", pdf,
        "Lines are medians across cycles of each cycle's statistic, "
        "not whole-run request percentiles.",
    )

    # Reliability.
    fig, ax = plt.subplots(figsize=(9, 5))

    for column, label, color in [
        ("failure_percent", "All request failures", BLUE),
        ("timeouts_percent", "Receive timeouts", ORANGE),
        ("send_errors_percent", "Send errors", GREEN),
        ("other_errors_percent", "Other errors", PURPLE),
    ]:
        add_line(ax, runs["N"], runs[column], label, color)

    ax.set_title("Request failures versus device count")
    ax.set_ylabel("Failed / attempted requests (%)")
    ax.set_ylim(bottom=0)
    style_axis(ax, versus_n=True)
    add_legend(ax)

    save_plot(
        fig, "request_failures_total_vs_N_1", pdf,
        "Calculated from summed request counts, not averaged percentages.",
    )

    # Payload throughput.
    fig, ax = plt.subplots(figsize=(9, 5))

    for column, label, color in [
        ("tx_payload_kB_s", "Bridge to emulators", BLUE),
        ("rx_payload_kB_s", "Emulators to bridge", ORANGE),
    ]:
        add_line(ax, runs["N"], runs[column], label, color)

    ax.set_title("ZMQ payload throughput versus device count")
    ax.set_ylabel("Payload throughput (kB/s)")
    ax.set_ylim(bottom=0)
    style_axis(ax, versus_n=True)
    add_legend(ax)

    save_plot(
        fig, "zmq_payload_combined_vs_N_1", pdf,
        "Time-weighted payload throughput. Excludes protocol overhead.",
    )

    # Acquisition/write rates.
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))

    for ax, column, title, ylabel in [
        (
            axes[0], "acquisitions_per_s",
            "Successful device acquisitions",
            "Acquisitions/s — all devices",
        ),
        (
            axes[1], "node_writes_per_s",
            "Successful OPC UA variable writes",
            "Writes/s — all variables",
        ),
    ]:
        add_line(ax, runs["N"], runs[column], title, BLUE)
        ax.set_title(title)
        ax.set_ylabel(ylabel)
        ax.set_ylim(bottom=0)
        style_axis(ax, versus_n=True)

    save_plot(
        fig, "operation_rates_total_vs_N_1", pdf,
        "Successful operations divided by summed cycle durations. "
        "Server-side writes do not establish Ignition delivery.",
    )

    # Processing time.
    fig, ax = plt.subplots(figsize=(9, 5))

    for metric, label, color in [
        ("parse_total_ms", "Response parsing", BLUE),
        ("update_total_ms", "OPC UA node updates", ORANGE),
    ]:
        selected = summary[summary["metric"] == metric]
        add_line(
            ax, selected["N"], selected["median"], label, color
        )

    ax.set_title("Bridge processing time versus device count")
    ax.set_ylabel("Median total duration per cycle (ms)")
    style_axis(ax, versus_n=True)
    add_legend(ax)

    save_plot(fig, "processing_combined_vs_N_1", pdf)


# ============================================================
# PREPARE SLOW-CYCLE DIAGNOSTICS
# ============================================================

cycle_tables = []
peak_rows = []

for item in datasets:
    data = item["data"].copy()
    baseline = data["cycle_s"].median()

    data["source_file"] = item["file"].name
    data["N"] = item["N"]
    data["baseline_cycle_s"] = baseline
    data["extra_cycle_s"] = data["cycle_s"] - baseline
    data["extra_cycle_percent"] = (
        100 * data["extra_cycle_s"] / baseline
    )
    data["slow_cycle"] = (
        data["extra_cycle_s"] > EXTRA_THRESHOLD_S
    )

    # Reconstruct successful request time.
    if {"successes", "mean_request_ms"}.issubset(data.columns):
        data["successful_requests_s"] = (
            data["successes"] * data["mean_request_ms"] / 1000
        )
        data.loc[
            data["successes"] == 0, "successful_requests_s"
        ] = 0.0

    needed = {
        "successful_requests_s",
        "parse_total_ms",
        "update_total_ms",
    }

    if needed.issubset(data.columns):
        data["unaccounted_s"] = (
            data["cycle_s"]
            - POLL_SLEEP_S
            - data["successful_requests_s"]
            - data["parse_total_ms"] / 1000
            - data["update_total_ms"] / 1000
        )

    cycle_tables.append(data)

    peak_rows.append({
        "N": item["N"],
        "cycles": len(data),
        "median_cycle_s": baseline,
        "threshold_extra_s": EXTRA_THRESHOLD_S,
        "slow_cycles": int(data["slow_cycle"].sum()),
        "slow_cycle_percent": 100 * data["slow_cycle"].mean(),
        "extra_p95_s": data["extra_cycle_s"].quantile(0.95),
        "extra_p99_s": data["extra_cycle_s"].quantile(0.99),
        "extra_max_s": data["extra_cycle_s"].max(),
        "relative_extra_p99_percent": (
            data["extra_cycle_percent"].quantile(0.99)
        ),
    })

peaks = pd.DataFrame(peak_rows).sort_values("N")
all_cycles = pd.concat(cycle_tables, ignore_index=True)

peaks.to_csv(PLOT_DIR / "slow_cycle_summary_1.csv", index=False)
all_cycles.to_csv(PLOT_DIR / "cycle_diagnostics_1.csv", index=False)

all_cycles[all_cycles["slow_cycle"]].sort_values(
    ["N", "extra_cycle_s"],
    ascending=[True, False],
).to_csv(PLOT_DIR / "slow_cycles_1.csv", index=False)

slowest = pd.concat(
    [
        data.nlargest(10, "cycle_s")
        for data in cycle_tables
    ],
    ignore_index=True,
)
slowest.to_csv(PLOT_DIR / "slowest_cycles_1.csv", index=False)

# ============================================================
# PDF 2: PEAK ANALYSIS
# ============================================================

threshold_ms = EXTRA_THRESHOLD_S * 1000

# Identical histogram bins across device counts.
all_extra_ms = all_cycles["extra_cycle_s"].to_numpy() * 1000

full_min = min(0.0, all_extra_ms.min())
full_max = max(
    threshold_ms * 2,
    all_extra_ms.max(),
)

full_bins = np.linspace(full_min, full_max, 51)
slow_bins = np.linspace(threshold_ms, full_max, 31)

with PdfPages(PLOT_DIR / "peak_analysis.pdf") as pdf:

    # ---------- Full distribution and slow cycles ----------

    for data in cycle_tables:
        n = int(data["N"].iloc[0])
        extra_ms = data["extra_cycle_s"].to_numpy() * 1000
        slow_ms = extra_ms[extra_ms > threshold_ms]

        fig, axes = plt.subplots(
            1, 2,
            figsize=(12, 4.8),
        )

        # All cycles, with no delays excluded from the range.
        axes[0].hist(
            extra_ms,
            bins=full_bins,
            color=BLUE,
            alpha=0.85,
            edgecolor="white",
            linewidth=0.4,
        )

        axes[0].axvline(
            0,
            color="#555555",
            linestyle=":",
            linewidth=1,
            label="Run median",
        )

        axes[0].axvline(
            threshold_ms,
            color=ORANGE,
            linestyle="--",
            linewidth=1.3,
            label=f"Slow threshold: +{threshold_ms:.0f} ms",
        )

        axes[0].set(
            title=f"All cycles: {len(extra_ms)}",
            xlabel="Cycle duration minus run median (ms)",
            ylabel="Number of cycles",
            xlim=(full_min, full_max),
        )
        add_legend(axes[0])

        # Only the slow cycles of interest.
        if len(slow_ms):
            axes[1].hist(
                slow_ms,
                bins=slow_bins,
                color=ORANGE,
                alpha=0.85,
                edgecolor="white",
                linewidth=0.4,
            )
        else:
            axes[1].text(
                0.5, 0.5,
                "No cycles exceeded the threshold",
                transform=axes[1].transAxes,
                ha="center",
                va="center",
                fontsize=11,
            )

        slow_percent = 100 * len(slow_ms) / len(extra_ms)

        axes[1].set(
            title=(
                f"Slow cycles: {len(slow_ms)}/{len(extra_ms)} "
                f"({slow_percent:.1f}%)"
            ),
            xlabel="Cycle duration minus run median (ms)",
            ylabel="Number of slow cycles",
            xlim=(threshold_ms, full_max),
        )

        for ax in axes:
            ax.set_ylim(bottom=0)
            ax.yaxis.set_major_locator(
                MaxNLocator(integer=True)
            )
            style_axis(ax)

        fig.suptitle(
            f"Cycle-delay distributions | N = {n}",
            fontsize=14,
        )

        save_plot(
            fig,
            f"cycle_delay_histograms_N{n}_1",
            pdf,
            f"Full observed delay range shown. Right panel includes "
            f"only cycles more than {threshold_ms:.0f} ms above "
            "their run median. Bins are identical across N.",
        )

    # ---------- Magnitude of delays versus N ----------

    fig, ax = plt.subplots(figsize=(9, 5))

    for column, label, color in [
        ("extra_p95_s", "P95", BLUE),
        ("extra_p99_s", "P99", ORANGE),
        ("extra_max_s", "Maximum observed", PURPLE),
    ]:
        add_line(
            ax,
            peaks["N"],
            peaks[column] * 1000,
            label,
            color,
        )

    ax.set_title("Extra cycle time versus device count")
    ax.set_ylabel("Cycle duration above run median (ms)")
    ax.set_ylim(bottom=0)
    style_axis(ax, versus_n=True)
    add_legend(ax)

    save_plot(
        fig,
        "extra_cycle_time_vs_N_1",
        pdf,
        "Percentiles describe all cycles after subtracting each "
        "run's median. Maximum depends on observation length.",
    )

    # ---------- Frequency of slow cycles versus N ----------

    fig, ax = plt.subplots(figsize=(9, 5))

    add_line(
        ax,
        peaks["N"],
        peaks["slow_cycle_percent"],
        "Slow cycles",
        BLUE,
    )

    ax.set_title(
        f"Cycles more than {threshold_ms:.0f} ms "
        "above their run median"
    )
    ax.set_ylabel("Slow cycles (%)")
    ax.set_ylim(bottom=0)
    style_axis(ax, versus_n=True)

    save_plot(
        fig,
        "slow_cycle_frequency_vs_N_1",
        pdf,
        "A fixed descriptive threshold, not an acceptance criterion. "
        "Consecutive slow cycles are counted individually.",
    )

    # ---------- Relative delay size versus N ----------

    fig, ax = plt.subplots(figsize=(9, 5))

    add_line(
        ax,
        peaks["N"],
        peaks["relative_extra_p99_percent"],
        "Relative P99 extra time",
        ORANGE,
    )

    ax.set_title("Relative extra cycle time versus device count")
    ax.set_ylabel("P99 extra time / run median (%)")
    ax.set_ylim(bottom=0)
    style_axis(ax, versus_n=True)

    save_plot(
        fig,
        "relative_extra_cycle_time_vs_N_1",
        pdf,
        "Extra time is measured relative to each run's own median.",
    )

    # ---------- Timing diagnostics for each N ----------

    for data in cycle_tables:
        n = int(data["N"].iloc[0])

        fig, axes = plt.subplots(
            2, 1,
            figsize=(10, 7),
            sharex=True,
        )

        # Remove the fixed sleep to expose the measured work/waiting.
        axes[0].plot(
            data["cycle"],
            (data["cycle_s"] - POLL_SLEEP_S) * 1000,
            color=BLUE,
            linewidth=1,
            label="Cycle time minus fixed sleep",
        )

        if "successful_requests_s" in data:
            axes[0].plot(
                data["cycle"],
                data["successful_requests_s"] * 1000,
                color=ORANGE,
                linewidth=1,
                label="Successful request time",
            )

        slow = data["slow_cycle"]

        if slow.any():
            axes[0].scatter(
                data.loc[slow, "cycle"],
                (
                    data.loc[slow, "cycle_s"] - POLL_SLEEP_S
                ) * 1000,
                color=PURPLE,
                s=22,
                zorder=3,
                label="Slow cycle",
            )

        axes[0].set_title(
            f"Cycle timing diagnostics | N = {n}"
        )
        axes[0].set_ylabel("Duration excluding fixed sleep (ms)")

        # Parsing and updates are already stored in milliseconds.
        for column, label, color, multiplier in [
            ("parse_total_ms", "Parsing", GREEN, 1),
            ("update_total_ms", "Node updates", ORANGE, 1),
            ("unaccounted_s", "Residual time", PURPLE, 1000),
        ]:
            if column in data:
                axes[1].plot(
                    data["cycle"],
                    data[column] * multiplier,
                    color=color,
                    linewidth=1,
                    label=label,
                )

        axes[1].set_xlabel("Polling cycle")
        axes[1].set_ylabel("Duration (ms)")

        for ax in axes:
            style_axis(ax)
            add_legend(ax)

        save_plot(
            fig,
            f"timing_diagnostics_N{n}_1",
            pdf,
            "Residual includes failed-request waiting and unmeasured "
            "work; it is not network delay alone. Cycle times rounded "
            "to 0.001 s introduce approximately ±0.5 ms rounding "
            "uncertainty into the residual.",
        )

        # Median OPC UA node-update time versus N.
    selected = summary[
        summary["metric"] == "update_total_ms"
    ].sort_values("N")

    if not selected.empty:
        fig, ax = plt.subplots(figsize=(9, 5))

        ax.plot(
            selected["N"],
            selected["median"],
            color=BLUE,
            marker="o",
            markersize=5,
            linewidth=2,
        )

        ax.set_title("OPC UA node-update time versus device count")
        ax.set_xlabel("Number of devices, N")
        ax.set_ylabel("Median total node-update time per cycle (ms)")
        ax.set_xlim(left=0)
        ax.set_ylim(bottom=0)
        style_axis(ax)

        save_plot(
            fig,
            "median_node_update_time_vs_N_1",
            pdf,
            "Each point is the median across cycles of the total "
            "time spent updating all selected devices' OPC UA nodes.",
        )

    rows = []

    for data in cycle_tables:
        baseline = data["cycle_s"].median()
        peak_count = int(
            (data["cycle_s"] - baseline > 0.5).sum()
        )

        rows.append({
            "N": int(data["N"].iloc[0]),
            "cycles": len(data),
            "peaks": peak_count,
            "peak_percent": 100 * peak_count / len(data),
        })

    peak_counts = pd.DataFrame(rows).sort_values("N")

    fig, ax = plt.subplots(figsize=(9, 5))

    ax.plot(
        peak_counts["N"],
        peak_counts["peak_percent"],
        color=BLUE,
        marker="o",
        markersize=5,
        linewidth=2,
    )

    for _, row in peak_counts.iterrows():
        ax.annotate(
            f"{int(row['peaks'])}/{int(row['cycles'])}",
            (row["N"], row["peak_percent"]),
            xytext=(0, 9),
            textcoords="offset points",
            ha="center",
            fontsize=8,
        )

    ax.set_title("Cycles more than 0.5 s above the run median")
    ax.set_xlabel("Number of devices, N")
    ax.set_ylabel("Cycles exceeding threshold (%)")
    ax.set_xlim(left=0)
    ax.set_ylim(
        0,
        max(1, peak_counts["peak_percent"].max() * 1.25),
    )
    style_axis(ax)

    save_plot(
        fig,
        "peaks_above_0p5s_vs_N_1",
        pdf,
        "Labels show qualifying cycles / analysed cycles. "
        "Each qualifying cycle is counted separately.",
    )

    peak_counts.to_csv(
        PLOT_DIR / "peaks_above_0p5s_vs_N_1.csv",
        index=False,
    )

data = pd.read_csv(DATA_DIR / "bridge_N110_1.csv")

print("Device counts:", data["devices"].unique())
print(data[["cpu_percent", "update_total_ms"]].describe())
fig, ax = plt.subplots(figsize=(7, 5))

ax.scatter(
    data["update_total_ms"],
    data["cpu_percent"],
    s=20,
    alpha=0.6,
)

ax.set(
    xlabel="Total OPC UA node-update time per cycle (ms)",
    ylabel="Bridge CPU usage (%)",
    title="CPU usage versus node-update time | N = 110",
)
ax.grid(alpha=0.2)

fig.tight_layout()
fig.savefig(PLOT_DIR / "cpu_vs_node_update_N110.png", dpi=300)
plt.close(fig)

data = pd.read_csv(DATA_DIR / "bridge_N110_1.csv")

print(data.nlargest(15, "cpu_percent")[
    [
        "cycle",
        "cpu_percent",
        "cycle_s",
        "mean_request_ms",
        "parse_total_ms",
        "update_total_ms",
    ]
].to_string(index=False))

print(f"\nMain PDF: {PLOT_DIR / 'all_bridge_plots.pdf'}")
print(f"Peak PDF: {PLOT_DIR / 'peak_analysis.pdf'}")
print(f"Individual figures and CSV summaries: {PLOT_DIR}")