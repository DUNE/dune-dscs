#!/usr/bin/env python3
"""Compare Ignition diagnostic cases, including cached and uncached timers.

Select two or more experiment folders with --case LABEL FOLDER.
Uses Ignition measurements. Optional --window measured reads bridge
cycle timestamps only to exclude setup and warm-up from the comparison.
"""

import argparse
import json
import math
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages

from plot_ignition_results import (
    COLORS, ROOT, cpu_spikes, load_case, resources_vs_n, save,
    style_axis,
)


def cpu_trace_panels(series, n):
    """Use the same CPU and time limits for every diagnostic case."""
    cpu_values = [frame["cpu_percent"].dropna() for _, frame, _ in series]
    maximum = max((v.max() for v in cpu_values if len(v)), default=0)
    limit = max(10, math.ceil(maximum / 10) * 10 + 5)
    time_limit = max(1 / 60, *(frame["minutes"].max()
                               for _, frame, _ in series))
    fig, axes = plt.subplots(
        len(series), 1, figsize=(10, 2.8 * len(series)),
        sharex=True, sharey=True, squeeze=False,
    )
    for ax, (label, frame, color) in zip(axes[:, 0], series):
        values = frame["cpu_percent"].dropna()
        ax.plot(frame["minutes"], frame["cpu_percent"], color=color,
                linewidth=0.9)
        ax.set(title=label, ylabel="Process CPU (%)",
               xlim=(0, time_limit), ylim=(0, limit))
        style_axis(ax)
        if not values.empty:
            ax.text(
                0.98, 0.86,
                f"Mean {values.mean():.2f}% | P95 {values.quantile(.95):.2f}%",
                transform=ax.transAxes, ha="right", fontsize=10,
                bbox={"facecolor": "white", "edgecolor": "none",
                      "alpha": 0.9},
            )
            if values.max() < limit / 5:
                inset = ax.inset_axes([0.58, 0.30, 0.38, 0.40])
                inset.plot(frame["minutes"], frame["cpu_percent"],
                           color=color, linewidth=0.7)
                inset.set(xlim=(0, time_limit),
                          ylim=(0, max(1, values.max() * 1.15)))
                inset.set_title("Zoom: different vertical scale", fontsize=8)
                inset.tick_params(labelsize=8)
                inset.grid(alpha=0.15)
    axes[-1, 0].set_xlabel("Time since selected-window start (minutes)")
    fig.suptitle(f"Ignition CPU by diagnostic case | N = {n}")
    return fig


def cpu_bars(series, n):
    """Show mean and P95 without assuming a particular case is a baseline."""
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.8))
    labels = [label for label, _, _ in series]
    for ax, title, statistic in [
        (axes[0], "Mean CPU", lambda values: values.mean()),
        (axes[1], "P95 CPU", lambda values: values.quantile(0.95)),
    ]:
        values = [statistic(frame["cpu_percent"].dropna())
                  for _, frame, _ in series]
        bars = ax.bar(range(len(series)), values,
                      color=[color for _, _, color in series], width=0.55)
        ax.bar_label(bars, labels=[f"{v:.2f}%" if np.isfinite(v) else "N/A"
                                   for v in values],
                     padding=5, fontsize=11)
        ax.set_xticks(range(len(series)), labels,
                      rotation=15 if len(series) > 2 else 0)
        valid = [value for value in values if np.isfinite(value)]
        ax.set(title=title, ylabel="Process CPU (%)",
               ylim=(0, max(valid, default=0) * 1.35 + 0.2))
        style_axis(ax)
    fig.suptitle(f"Ignition CPU summary | N = {n}")
    return fig


def cpu_distribution(series, n):
    """Plot cumulative sample percentages, retaining the full CPU range."""
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8), sharey=True)
    maximum = 0
    for label, frame, color in series:
        values = np.sort(frame["cpu_percent"].dropna().to_numpy())
        if not len(values):
            continue
        maximum = max(maximum, values[-1])
        x = np.unique(np.r_[0.0, values])
        cumulative = 100 * \
            np.searchsorted(values, x, side="right") / len(values)
        for ax in axes:
            ax.step(x, cumulative, where="post", color=color,
                    linewidth=1.8, label=label)
    axes[0].set(title="Low-CPU region: 0–5%", xlim=(0, 5),
                ylabel="Samples at or below CPU level (%)")
    axes[1].set(title="Full observed range",
                xlim=(0, max(5, maximum * 1.05)))
    for ax in axes:
        ax.set(xlabel="Process CPU usage (%)", ylim=(0, 102))
        style_axis(ax)
    axes[1].legend(fontsize=11, loc="lower right")
    fig.suptitle(f"Ignition CPU distribution | N = {n}")
    return fig


def memory_trace(series, n):
    fig, ax = plt.subplots(figsize=(10, 4.8))
    values = []
    for label, frame, color in series:
        ram = frame["rss_mb"].dropna()
        if ram.empty:
            continue
        values.extend(ram.to_numpy())
        ax.plot(frame["minutes"], frame["rss_mb"], color=color,
                linewidth=1.2, label=f"{label} (median {ram.median():.2f} MB)")
    if values:
        padding = max(0.5, (max(values) - min(values)) * 0.15)
        ax.set_ylim(max(0, min(values) - padding), max(values) + padding)
    ax.set(title=f"Ignition resident memory | N = {n}",
           xlabel="Time since selected-window start (minutes)",
           ylabel="Resident memory (MB)")
    style_axis(ax)
    ax.legend(fontsize=11)
    return fig


def report_comparison(cases, args):
    destination = args.output_dir
    destination.mkdir(parents=True, exist_ok=True)
    combined = pd.concat([
        case[4].assign(case=case[0]) for case in cases
    ], ignore_index=True)
    combined.to_csv(destination / "summary.csv", index=False)
    series = [(case[0], case[4], case[2]) for case in cases]
    window_note = (
        f"Separate experiments. Resource window: {args.window}. "
        "Time axes start at each selected window. "
        "100% process CPU = one logical CPU."
    )
    note = window_note + " Lines: medians; bands: P5–P95 across samples."
    with PdfPages(destination / "ignition_timer_comparison.pdf") as pdf:
        save(resources_vs_n(series), pdf, destination, "resources_vs_N",
             args, note)
        save(cpu_spikes(series, args), pdf, destination, "cpu_spikes_vs_N",
             args, window_note)
        measured = [
            (label, summary.loc[summary["tag_samples"].gt(0)], color)
            for label, summary, color in series
        ]
        measured = [item for item in measured if not item[1].empty]
        if measured:
            fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
            for label, summary, color in measured:
                axes[0].plot(
                    summary["N"], summary["collector_ms_median"],
                    marker="o", color=color, label=label,
                )
                axes[0].fill_between(
                    summary["N"].to_numpy(),
                    summary["collector_ms_p05"].to_numpy(),
                    summary["collector_ms_p95"].to_numpy(),
                    color=color, alpha=0.15,
                )
                axes[1].plot(
                    summary["N"], summary["all_good_samples_pct"],
                    marker="o", color=color, label=label,
                )
            axes[0].set(ylabel="Diagnostic collection time (ms)")
            axes[1].set(ylabel="Complete, all-good snapshots (%)",
                        ylim=(-2, 105))
            for ax in axes:
                ax.set_xlabel("Number of emulators, N")
                style_axis(ax)
                ax.legend(fontsize=11)
            fig.suptitle("Diagnostic collection and tag quality by case")
            save(fig, pdf, destination, "collection_quality_vs_N", args,
                 "Only cases with tag snapshots appear here. Collection "
                 "duration is elapsed diagnostic time, not thread CPU time.")
        common = set.intersection(*(set(case[3]) for case in cases))
        print(f"Device counts shared by all cases: {sorted(common)}")
        for n in sorted(common):
            samples = [
                (case[0], case[3][n][0], case[2]) for case in cases
            ]
            save(cpu_trace_panels(samples, n), pdf, destination,
                 f"cpu_over_time_N{n}", args,
                 window_note + " Main panels use identical scales; "
                 "insets are zooms.")
            save(cpu_bars(samples, n), pdf, destination,
                 f"cpu_summary_N{n}", args,
                 "Both panels start at zero; vertical scales differ. "
                 "100% CPU = one logical CPU.")
            save(cpu_distribution(samples, n), pdf, destination,
                 f"cpu_distribution_N{n}", args,
                 "Left panel zooms into 0–5% CPU; the right panel shows "
                 "all observed values. Samples are equally weighted.")
            save(memory_trace(samples, n), pdf, destination,
                 f"memory_comparison_N{n}", args,
                 "Vertical axis is zoomed. RSS measures resident process "
                 "memory, not JVM heap usage. " + window_note)
    print(f"Saved {destination / 'ignition_timer_comparison.pdf'}")


def measured_windows(folder, devices):
    """Recover measured-cycle windows, without plotting bridge metrics."""
    from plot_bridge_results import load_bridge_data

    windows = {}
    for item in load_bridge_data(folder, 0, devices):
        data = item["data"]
        if "time_utc" not in data:
            raise ValueError(f"{item['file']}: missing time_utc")
        times = pd.to_datetime(data["time_utc"], utc=True,
                               format="ISO8601", errors="coerce")
        if times.isna().any() or not times.is_monotonic_increasing:
            raise ValueError(f"{item['file']}: invalid cycle timestamps")
        windows[item["N"]] = (
            times.iloc[0] - pd.to_timedelta(data["cycle_s"].iloc[0], unit="s"),
            times.iloc[-1],
        )
    return windows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case", nargs=2, action="append", required=True,
        metavar=("LABEL", "FOLDER"),
    )
    parser.add_argument(
        "--output-dir", type=Path,
        default=ROOT / "figures" / "ignition_timer_comparison",
    )
    parser.add_argument(
        "--window", choices=("all", "measured"), default="all",
        help=(
            "All resource samples, or only samples during "
            "measured bridge cycles"
        ),
    )
    parser.add_argument("--devices", type=int, nargs="+")
    parser.add_argument("--spike-threshold", type=float, default=50)
    parser.add_argument("--no-images", action="store_true")
    args = parser.parse_args()
    if len(args.case) < 2:
        parser.error("Provide at least two --case LABEL FOLDER entries")
    labels = [label.strip() for label, _ in args.case]
    if not all(labels) or len(set(labels)) != len(labels):
        parser.error("Use nonempty, unique case labels")
    if not math.isfinite(args.spike_threshold) or args.spike_threshold < 0:
        parser.error("--spike-threshold must be finite and nonnegative")
    if args.devices and any(n <= 0 for n in args.devices):
        parser.error("--devices must contain positive numbers")
    args.output_dir = args.output_dir.expanduser().resolve()
    plt.rcParams.update({
        "font.size": 11, "axes.titlesize": 13,
        "axes.spines.top": False, "axes.spines.right": False,
        "legend.frameon": False,
    })
    cases = []
    for index, (label, folder) in enumerate(args.case):
        folder = Path(folder).expanduser().resolve()
        windows = (
            measured_windows(folder, args.devices)
            if args.window == "measured" else None
        )
        runs, summary = load_case(folder, args, windows)
        cases.append(
            (label, folder, COLORS[index % len(COLORS)], runs, summary))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "plot_settings.json").write_text(
        json.dumps({
            "cases": [{"label": case[0], "folder": str(case[1])}
                      for case in cases],
            "devices": args.devices,
            "resource_window": args.window,
            "spike_threshold_percent": args.spike_threshold,
        }, indent=2) + "\n", encoding="utf-8",
    )
    report_comparison(cases, args)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, pd.errors.ParserError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
