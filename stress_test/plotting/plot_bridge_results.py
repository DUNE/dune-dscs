#!/usr/bin/env python3
"""Plot bridge diagnostics, slow cycles and optional Ignition resources.

Run from stress_test with:
    python plotting/plot_bridge_results.py --data-dir results/bridge_only

Input names must be bridge_N<number>.csv. One folder represents one
experiment. Source measurements are read only; reports are overwritten
when the same output folder is reused. Run with --help for options.
"""

import argparse
import json
import math
import re
import sys
import textwrap
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.ticker import MaxNLocator

matplotlib.use("Agg")

ROOT = Path(__file__).resolve().parents[1]
BLUE = "#2563eb"
ORANGE = "#d97706"
GREEN = "#059669"
PURPLE = "#9333ea"

METRICS = {
    "variables": (
        "Configured variables", "Number of variables"
    ),
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
    "attempts": ("Requests attempted per cycle", "Requests per cycle"),
    "successes": (
        "Successful acquisitions per cycle", "Acquisitions per cycle"
    ),
    "node_writes": ("OPC UA variable writes per cycle", "Writes per cycle"),
}


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
        ax.legend(fontsize=12)


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


def load_bridge_data(data_dir, skip_cycles, selected_devices):
    """Load one explicitly selected bridge file per device count."""
    pattern = re.compile(r"bridge_N(\d+)\.csv")
    datasets = []

    for file in data_dir.glob("bridge_N*.csv"):
        match = pattern.fullmatch(file.name)
        if match is None:
            continue

        if selected_devices and int(match.group(1)) not in selected_devices:
            continue

        try:
            data = pd.read_csv(file)
        except pd.errors.EmptyDataError:
            print(f"Skipping empty file: {file.name}")
            continue

        raw_cycles = len(data)
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
        data = data[data["cycle"] > skip_cycles]
        data = data.sort_values("cycle")

        if data.empty:
            print(f"No usable cycles: {file.name}")
            continue

        counts = data["devices"].dropna().unique()

        if (
            data["devices"].isna().any()
            or len(counts) != 1
            or counts[0] <= 0
            or counts[0] != int(counts[0])
        ):
            raise ValueError(f"{file.name}: invalid device counts")

        n = int(counts[0])

        if n != int(match.group(1)):
            raise ValueError(f"{file.name}: filename and recorded N disagree.")

        if data["cycle"].lt(1).any() or data["cycle"].mod(1).ne(0).any():
            raise ValueError(
                f"{file.name}: cycle numbers must be positive integers.")

        if data["cycle"].duplicated().any():
            raise ValueError(f"{file.name}: duplicate cycle numbers")

        datasets.append({
            "file": file,
            "N": n,
            "data": data,
            "raw_cycles": raw_cycles,
        })

    datasets.sort(key=lambda item: item["N"])

    if not datasets:
        raise ValueError(f"No usable bridge_N<number>.csv files in {data_dir}")

    counts = [item["N"] for item in datasets]
    if len(counts) != len(set(counts)):
        raise ValueError("Multiple selected files have the same N.")

    print("\nFiles used:")
    for item in datasets:
        print(
            f"  {item['file'].name}: "
            f"N={item['N']}, {len(item['data'])} cycles"
        )

    return datasets


def summarize_metrics(datasets):
    """Summarise per-cycle values separately for each device count."""
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
    return summary


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


def summarize_runs(datasets):
    """Calculate whole-run rates and failures from measured counts and time."""
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
            row[f"{column}_total"] = (
                data[column].sum(min_count=len(data))
                if column in data else np.nan
            )

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
    return runs


def plot_bridge_results(datasets, summary, runs, comparison, args):
    """Write cycle, scaling and resource figures to the main report."""
    with PdfPages(args.output_dir / "bridge_results.pdf") as pdf:

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
                fig, f"{item['file'].stem}_cycle_time", pdf, args
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

            note = (
                "Bands show variation across cycles, "
                "not confidence intervals."
            )
            if metric == "cpu_percent":
                note += " 100% CPU = one logical CPU."
            elif metric in {
                "request_median_ms", "request_p95_ms", "request_p99_ms"
            }:
                note += " These are per-cycle request statistics."

            save_plot(fig, f"{metric}_vs_N", pdf, args, note)

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
            fig, "resources_vs_N", pdf, args,
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
            fig, "request_latency_combined_vs_N", pdf, args,
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
            fig, "request_failures_total_vs_N", pdf, args,
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
            fig, "zmq_payload_combined_vs_N", pdf, args,
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
            fig, "operation_rates_total_vs_N", pdf, args,
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

        save_plot(fig, "processing_combined_vs_N", pdf, args)

        # Compact totals are easier to use on slides than three separate pages.
        fig, axes = plt.subplots(1, 3, figsize=(11, 3.2), sharey=True)
        for ax, column, title in [
            (axes[0], "timeouts_total", "Receive timeouts"),
            (axes[1], "send_errors_total", "Send errors"),
            (axes[2], "other_errors_total", "Other errors"),
        ]:
            add_line(ax, runs["N"], runs[column], title, BLUE)
            ax.set_title(title)
            ax.set_ylim(bottom=0)
            ax.yaxis.set_major_locator(MaxNLocator(integer=True))
            style_axis(ax, versus_n=True)
            values = runs[column].dropna()
            if len(values) == len(runs) and values.eq(0).all():
                ax.set_ylim(-0.05, 1)
                ax.text(0.5, 0.55, "0 recorded", transform=ax.transAxes,
                        ha="center", fontsize=15, fontweight="bold")
            elif values.empty:
                ax.text(0.5, 0.55, "Not measured", transform=ax.transAxes,
                        ha="center", fontsize=13)
        axes[0].set_ylabel("Total events per run")
        save_plot(fig, "bridge_errors_vs_N_compact", pdf, args,
                  "Totals over analysed cycles for each device count.")

        for item in datasets:
            data = item["data"]
            required = {"update_total_ms", "cpu_percent"}
            if not required.issubset(data.columns):
                continue
            selected = data.dropna(subset=list(required))
            if selected.empty:
                continue
            fig, ax = plt.subplots(figsize=(7, 5))
            ax.scatter(selected["update_total_ms"], selected["cpu_percent"],
                       s=20, alpha=0.6, color=BLUE)
            ax.set(title=f"Bridge CPU and node-update time | N = {item['N']}",
                   xlabel="Total OPC UA node-update time per cycle (ms)",
                   ylabel="Bridge process CPU usage (%)")
            style_axis(ax)
            save_plot(fig, f"cpu_vs_node_update_N{item['N']}", pdf, args,
                      "Each point represents one analysed polling cycle.")

        if comparison is not None:
            plot_resource_comparisons(comparison, pdf, args)


def prepare_peak_analysis(datasets, args):
    """Calculate delays relative to each run median and export tables."""
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
            data["extra_cycle_s"] > args.slow_threshold
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
                - args.poll_sleep
                - data["successful_requests_s"]
                - data["parse_total_ms"] / 1000
                - data["update_total_ms"] / 1000
            )

        cycle_tables.append(data)

        peak_rows.append({
            "N": item["N"],
            "cycles": len(data),
            "median_cycle_s": baseline,
            "threshold_extra_s": args.slow_threshold,
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

    peaks.to_csv(args.output_dir / "slow_cycle_summary.csv", index=False)
    all_cycles.to_csv(args.output_dir / "cycle_diagnostics.csv", index=False)

    all_cycles[all_cycles["slow_cycle"]].sort_values(
        ["N", "extra_cycle_s"],
        ascending=[True, False],
    ).to_csv(args.output_dir / "slow_cycles.csv", index=False)

    slowest = pd.concat(
        [
            data.nlargest(10, "cycle_s")
            for data in cycle_tables
        ],
        ignore_index=True,
    )
    slowest.to_csv(args.output_dir / "slowest_cycles.csv", index=False)

    return cycle_tables, peaks


def plot_peak_analysis(cycle_tables, peaks, summary, args):
    """Write histograms, slow-cycle frequencies and timing diagnostics."""
    threshold_ms = args.slow_threshold * 1000

    # Identical histogram bins across device counts.
    all_extra_ms = np.concatenate(
        [data["extra_cycle_s"].to_numpy() for data in cycle_tables]) * 1000

    full_min = min(0.0, all_extra_ms.min())
    full_max = max(
        threshold_ms * 2,
        all_extra_ms.max(),
    )

    full_bins = np.linspace(full_min, full_max, 51)
    slow_bins = np.linspace(threshold_ms, full_max, 31)

    with PdfPages(args.output_dir / "bridge_peak_analysis.pdf") as pdf:

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
                f"cycle_delay_histograms_N{n}",
                pdf, args,
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
            "extra_cycle_time_vs_N",
            pdf, args,
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
            "slow_cycle_frequency_vs_N",
            pdf, args,
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
            "relative_extra_cycle_time_vs_N",
            pdf, args,
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
                (data["cycle_s"] - args.poll_sleep) * 1000,
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
                        data.loc[slow, "cycle_s"] - args.poll_sleep
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
                f"timing_diagnostics_N{n}",
                pdf, args,
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
                "median_node_update_time_vs_N",
                pdf, args,
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

        for label_index, (_, row) in enumerate(peak_counts.iterrows()):
            ax.annotate(
                f"{int(row['peaks'])}/{int(row['cycles'])}",
                (row["N"], row["peak_percent"]),
                xytext=(0, 9 + 13 * (label_index % 2)),
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
            "peaks_above_0p5s_vs_N",
            pdf, args,
            "Labels show qualifying cycles / analysed cycles. "
            "Each qualifying cycle is counted separately.",
        )

        peak_counts.to_csv(
            args.output_dir / "peaks_above_0p5s_vs_N.csv",
            index=False,
        )


def save_plot(fig, name, pdf, args, note=None):
    """Add a report page and optionally save an individual image."""
    if note:
        fig.text(
            0.5, 0.01, textwrap.fill(note, width=115),
            ha="center", va="bottom", fontsize=9,
        )
    fig.tight_layout(rect=(0, 0.12 if note else 0, 1, 1))
    pdf.savefig(fig)
    if not args.no_images:
        fig.savefig(args.output_dir / f"{name}.png", dpi=200)
    plt.close(fig)


def load_ignition_resources(folder, selected_devices):
    """Read Gateway resources from one explicitly selected experiment."""
    path = folder / "ignition_resources.csv"
    data = pd.read_csv(path)
    required = {"N", "cpu_percent", "rss_mb"}
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"{path}: missing columns {sorted(missing)}")
    for column in required:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.replace([np.inf, -np.inf], np.nan)
    data = data.dropna(subset=["N"])
    if data["N"].le(0).any() or data["N"].mod(1).ne(0).any():
        raise ValueError(f"{path}: N must contain positive integers")
    if selected_devices:
        data = data[data["N"].isin(selected_devices)]
    rows = []
    for n, group in data.groupby("N"):
        for column in ("cpu_percent", "rss_mb"):
            values = group[column].dropna()
            if values.empty:
                continue
            rows.append({
                "N": int(n), "metric": column, "samples": len(values),
                "mean": values.mean(), "median": values.median(),
                "p05": values.quantile(0.05),
                "p95": values.quantile(0.95),
                "maximum": values.max(),
            })
    if not rows:
        raise ValueError(f"No valid resource measurements in {path}")
    print(f"Ignition resources: {path}")
    return pd.DataFrame(rows)


def plot_resource_comparisons(comparison, pdf, args):
    """Keep each component's own device counts when comparing resources."""
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    for ax, metric, title, unit in [
        (axes[0], "cpu_percent", "CPU usage", "Process CPU usage (%)"),
        (axes[1], "ram_mb", "Resident memory", "Resident memory (MB)"),
    ]:
        for component, frame, color in comparison:
            key = metric
            if component == "Ignition" and metric == "ram_mb":
                key = "rss_mb"
            values = frame.loc[frame["metric"].eq(key)].sort_values("N")
            if values.empty:
                continue
            ax.fill_between(
                values["N"].to_numpy(), values["p05"].to_numpy(),
                values["p95"].to_numpy(), color=color, alpha=0.15,
            )
            ax.plot(
                values["N"], values["median"], marker="o",
                linewidth=2, markersize=4, color=color, label=component,
            )
        ax.set(title=title, ylabel=unit, ylim=(0, None))
        style_axis(ax, versus_n=True)
        ax.legend(
            loc="upper left" if metric == "cpu_percent" else "center right",
            fontsize=12, frameon=False,
        )
    save_plot(
        fig, "bridge_ignition_resources_vs_N", pdf, args,
        "Lines: medians. Bands: P5–P95 across samples, not confidence "
        "intervals. 100% CPU = one logical CPU. Ignition uses all resource "
        "samples in the selected experiment; these may include warm-up. "
        "The two folders may represent separate test runs.",
    )


def parse_arguments():
    """Select experiment folders without hard-coded historical datasets."""
    parser = argparse.ArgumentParser(
        description=(
            "Create bridge performance and peak-analysis reports from "
            "bridge_N<number>.csv files. Optionally compare "
            "Ignition resources."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--data-dir", type=Path, default=ROOT / "results" / "bridge_only",
        help="Folder containing the bridge CSV files for one experiment",
    )
    parser.add_argument(
        "--output-dir", type=Path,
        help="Report folder; default: figures/<experiment folder name>",
    )
    parser.add_argument(
        "--ignition-dir", type=Path,
        help="Optional experiment folder containing ignition_resources.csv",
    )
    parser.add_argument(
        "--devices", type=int, nargs="+",
        help="Only analyse these device counts; default: all available",
    )
    parser.add_argument(
        "--skip-cycles", type=int, default=0,
        help=(
            "Exclude cycle numbers <= this value; "
            "warm-up is normally already excluded"
        ),
    )
    parser.add_argument(
        "--slow-threshold", type=float, default=0.1,
        help="Slow cycle: seconds above that experiment's median cycle time",
    )
    parser.add_argument(
        "--poll-sleep", type=float, default=1.0,
        help=(
            "Fixed sleep included in cycle_s, in seconds; "
            "used for timing breakdown"
        ),
    )
    parser.add_argument(
        "--no-images", action="store_true",
        help="Save the two PDFs and CSV summaries without individual PNGs",
    )
    args = parser.parse_args()
    if args.skip_cycles < 0:
        parser.error("--skip-cycles must be nonnegative")
    if not math.isfinite(args.slow_threshold) or args.slow_threshold <= 0:
        parser.error("--slow-threshold must be finite and positive")
    if not math.isfinite(args.poll_sleep) or args.poll_sleep < 0:
        parser.error("--poll-sleep must be finite and nonnegative")
    if args.devices and any(n <= 0 for n in args.devices):
        parser.error("--devices must contain positive device counts")
    args.data_dir = args.data_dir.expanduser().resolve()
    if not args.data_dir.is_dir():
        parser.error(f"Data directory does not exist: {args.data_dir}")
    args.output_dir = (
        args.output_dir.expanduser().resolve() if args.output_dir
        else ROOT / "figures" / args.data_dir.name
    )
    if args.ignition_dir:
        args.ignition_dir = args.ignition_dir.expanduser().resolve()
    return args


def main():
    args = parse_arguments()
    datasets = load_bridge_data(
        args.data_dir, args.skip_cycles, args.devices,
    )
    if args.devices:
        missing = set(args.devices) - {item["N"] for item in datasets}
        if missing:
            raise ValueError(f"No usable bridge files for N={sorted(missing)}")
    summary = summarize_metrics(datasets)
    runs = summarize_runs(datasets)
    comparison = None
    if args.ignition_dir:
        ignition = load_ignition_resources(args.ignition_dir, args.devices)
        comparison = [
            ("Bridge", summary, BLUE), ("Ignition", ignition, ORANGE),
        ]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({
        "font.size": 11, "axes.titlesize": 14,
        "axes.spines.top": False, "axes.spines.right": False,
        "legend.frameon": False,
    })
    summary.to_csv(args.output_dir / "bridge_summary.csv", index=False)
    runs.to_csv(args.output_dir / "bridge_run_totals.csv", index=False)
    if comparison:
        comparison[1][1].to_csv(
            args.output_dir / "ignition_resource_summary.csv", index=False,
        )
    pd.DataFrame([
        {"source_file": str(item["file"].resolve()), "N": item["N"],
         "raw_cycles": item["raw_cycles"],
         "analysed_cycles": len(item["data"])}
        for item in datasets
    ]).to_csv(args.output_dir / "input_files.csv", index=False)
    settings = {
        key: str(value) if isinstance(value, Path) else value
        for key, value in vars(args).items()
    }
    (args.output_dir / "plot_settings.json").write_text(
        json.dumps(settings, indent=2) + "\n", encoding="utf-8",
    )
    cycle_tables, peaks = prepare_peak_analysis(datasets, args)
    plot_bridge_results(datasets, summary, runs, comparison, args)
    plot_peak_analysis(cycle_tables, peaks, summary, args)
    print(f"\nReports saved in {args.output_dir}")
    print("  bridge_results.pdf")
    print("  bridge_peak_analysis.pdf")
    print("CSV summaries are saved in the same folder.")
    if not args.no_images:
        print("Individual figures are also saved as PNGs.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, pd.errors.ParserError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
