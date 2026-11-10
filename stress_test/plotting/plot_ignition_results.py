#!/usr/bin/env python3
"""Plot one Ignition experiment, without reading bridge measurements.

Run from stress_test:
    python plotting/plot_ignition_results.py \
        --data-dir results/diagnostics_disabled

Requires ignition_resources.csv. ignition_tag_diagnostics.csv is optional.
All resource samples for each N are used, including setup and warm-up if
present. Use one experiment per folder. Inputs are never modified.
Reports with matching names are overwritten when rerun.
"""

import argparse
import json
import math
import sys
import textwrap
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages

matplotlib.use("Agg")

ROOT = Path(__file__).resolve().parents[1]
COLORS = ("#2563eb", "#d97706", "#059669", "#9333ea", "#dc2626")
METRICS = {
    "cpu_percent": "Gateway process CPU (%)",
    "rss_mb": "Gateway resident memory (MB)",
}
QUALITY = ("good", "uncertain", "bad", "missing")
QUALITY_COLORS = ("#059669", "#d97706", "#dc2626", "#64748b")


def read_csv(path, numeric_columns):
    """Keep missing measurements distinct from measured zero values."""
    data = pd.read_csv(path)
    required = {"time_utc", *numeric_columns}
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"{path}: missing columns {sorted(missing)}")
    data["time_utc"] = pd.to_datetime(
        data["time_utc"], utc=True, format="ISO8601", errors="coerce",
    )
    for column in numeric_columns:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.replace([np.inf, -np.inf], np.nan)
    valid = data["time_utc"].notna()
    if "N" in data:
        valid &= data["N"].gt(0) & data["N"].mod(1).eq(0)
    if (~valid).any():
        print(f"{path.name}: excluded {(~valid).sum()} invalid rows")
    return data.loc[valid].sort_values("time_utc").copy()


def load_tags(folder):
    path = folder / "ignition_tag_diagnostics.csv"
    if not path.is_file():
        return None
    counts = [f"{kind}_tags" for kind in QUALITY]
    numeric = ["N", "expected_tags", "extra_tags", "collector_ms", *counts]
    data = read_csv(path, numeric)
    # The four categories partition expected tags; extras are separate.
    integers = ["expected_tags", "extra_tags", *counts]
    valid = (
        data["expected_tags"].gt(0)
        & data[integers].ge(0).all(axis=1)
        & data[integers].mod(1).eq(0).all(axis=1)
        & data[counts].sum(axis=1).eq(data["expected_tags"])
    )
    if (~valid).any():
        print(f"{path.name}: excluded {(~valid).sum()} invalid tag snapshots")
    data = data.loc[valid].copy()
    data.loc[data["collector_ms"].lt(0), "collector_ms"] = np.nan
    if "connection_state" not in data:
        raise ValueError(f"{path}: missing connection_state")
    data["connection_state"] = (
        data["connection_state"].fillna("UNKNOWN").astype(str)
        .str.strip().str.upper()
    )
    for kind in QUALITY:
        data[f"{kind}_pct"] = (
            100 * data[f"{kind}_tags"] / data["expected_tags"]
        )
    return data


def add_statistics(row, prefix, values):
    values = values.dropna()
    row[f"{prefix}_samples"] = len(values)
    for name, value in {
        "mean": values.mean(), "median": values.median(),
        "p05": values.quantile(0.05), "p95": values.quantile(0.95),
        "max": values.max(),
    }.items():
        row[f"{prefix}_{name}"] = value


def load_case(folder, args):
    resources = read_csv(
        folder / "ignition_resources.csv", ["N", *METRICS],
    )
    for metric in METRICS:
        resources.loc[resources[metric].lt(0), metric] = np.nan
    tags = load_tags(folder)
    runs = {}
    rows = []
    for n, samples in resources.groupby("N"):
        n = int(n)
        if args.devices and n not in args.devices:
            continue
        samples = samples.copy()
        start = samples["time_utc"].min()
        end = samples["time_utc"].max()
        if "pid" in samples and samples["pid"].nunique() > 1:
            print(f"WARNING: {folder.name}, N={n}: multiple Gateway PIDs")
        samples["minutes"] = (
            samples["time_utc"] - start
        ).dt.total_seconds() / 60
        row = {
            "N": n,
            "start_utc": start.isoformat(), "end_utc": end.isoformat(),
            "resource_samples": len(samples),
        }
        for metric in METRICS:
            add_statistics(row, metric, samples[metric])
        cpu = samples["cpu_percent"].dropna()
        row["cpu_above_threshold_pct"] = (
            100 * cpu.gt(args.spike_threshold).mean()
        )
        quality = pd.DataFrame()
        row["tag_samples"] = 0
        if tags is not None:
            quality = tags.loc[
                tags["N"].eq(n) & tags["time_utc"].between(start, end)
            ].copy()
        if not quality.empty:
            if "run_id" in quality and quality["run_id"].nunique() > 1:
                raise ValueError(
                    f"{folder}, N={n}: multiple tag run IDs in window. "
                    "Use a folder containing one experiment."
                )
            quality["minutes"] = (
                quality["time_utc"] - start
            ).dt.total_seconds() / 60
            row["tag_samples"] = len(quality)
            for kind in QUALITY:
                row[f"{kind}_tag_pct"] = quality[f"{kind}_pct"].mean()
            for column in ("expected_tags", "missing_tags", "extra_tags"):
                add_statistics(row, column, quality[column])
            row["all_good_samples_pct"] = 100 * (
                quality["good_tags"].eq(quality["expected_tags"])
                & quality["missing_tags"].eq(0)
                & quality["extra_tags"].eq(0)
            ).mean()
            row["connected_samples_pct"] = 100 * (
                quality["connection_state"].eq("CONNECTED")
            ).mean()
            add_statistics(row, "collector_ms", quality["collector_ms"])
        runs[n] = (samples, quality)
        rows.append(row)
    if not rows:
        raise ValueError(f"{folder}: no valid Ignition resource measurements")
    summary = pd.DataFrame(rows).sort_values("N")
    print(f"{folder}: N={summary['N'].tolist()}")
    return runs, summary


def style_axis(ax):
    ax.grid(axis="y", alpha=0.2)
    ax.set_axisbelow(True)
    ax.ticklabel_format(axis="y", style="plain", useOffset=False)


def save(fig, pdf, folder, name, args, note=None):
    if note:
        fig.text(
            0.5, 0.01, textwrap.fill(note, 110), ha="center",
            va="bottom", fontsize=9,
        )
    fig.tight_layout(rect=(0, 0.12 if note else 0, 1, 0.95))
    pdf.savefig(fig)
    if not args.no_images:
        fig.savefig(folder / f"{name}.png", dpi=200)
    plt.close(fig)


def resources_vs_n(series):
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    for ax, (metric, ylabel) in zip(axes, METRICS.items()):
        for label, summary, color in series:
            ax.plot(
                summary["N"], summary[f"{metric}_median"],
                color=color, marker="o", markersize=4, label=label,
            )
            ax.fill_between(
                summary["N"].to_numpy(),
                summary[f"{metric}_p05"].to_numpy(),
                summary[f"{metric}_p95"].to_numpy(),
                color=color, alpha=0.15,
            )
        ax.set(xlabel="Number of emulators, N", ylabel=ylabel)
        if metric == "cpu_percent":
            ax.set_ylim(bottom=0)
        style_axis(ax)
        ax.legend(fontsize=12, loc="best")
    fig.suptitle("Ignition resources versus device count")
    return fig


def cpu_spikes(series, args):
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.6))
    for ax, column, ylabel in [
        (axes[0], "cpu_percent_mean", "Mean process CPU (%)"),
        (axes[1], "cpu_percent_p95", "Process CPU P95 (%)"),
        (axes[2], "cpu_above_threshold_pct",
         f"Samples above {args.spike_threshold:g}% CPU (%)"),
    ]:
        for label, summary, color in series:
            ax.plot(
                summary["N"], summary[column], marker="o",
                markersize=4, color=color, label=label,
            )
        ax.set(xlabel="Number of emulators, N", ylabel=ylabel)
        ax.set_ylim(bottom=0)
        style_axis(ax)
        ax.legend(fontsize=11)
    fig.suptitle("Ignition CPU usage and high-CPU samples")
    return fig


def over_time(series, n):
    fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    for ax, (metric, ylabel) in zip(axes, METRICS.items()):
        for label, samples, color in series:
            ax.plot(
                samples["minutes"], samples[metric], color=color,
                linewidth=0.9, alpha=0.85, label=label,
            )
        ax.set_ylabel(ylabel)
        if metric == "cpu_percent":
            ax.set_ylim(bottom=0)
        style_axis(ax)
        ax.legend(fontsize=12)
    axes[-1].set_xlabel("Minutes since start of each selected window")
    fig.suptitle(f"Ignition resources over time | N = {n}")
    return fig


def tag_plots(summary, pdf, folder, args):
    measured = summary.loc[summary["tag_samples"].gt(0)]
    if measured.empty:
        return
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    for kind, color in zip(QUALITY, QUALITY_COLORS):
        axes[0].plot(
            measured["N"], measured[f"{kind}_tag_pct"],
            marker="o", color=color, label=kind.capitalize(),
        )
    axes[0].set(ylabel="Mean share of expected tags (%)", ylim=(-2, 105))
    axes[0].legend(fontsize=12)
    for column, label, color in [
        ("all_good_samples_pct",
         "Complete, all good, no extra tags", COLORS[0]),
        ("connected_samples_pct", "OPC UA CONNECTED", COLORS[2]),
    ]:
        axes[1].plot(
            measured["N"], measured[column], marker="o",
            label=label, color=color,
        )
    axes[1].set(ylabel="Periodic snapshots (%)", ylim=(-2, 105))
    axes[1].legend(fontsize=10, loc="lower left")
    for ax in axes:
        ax.set_xlabel("Number of emulators, N")
        style_axis(ax)
    fig.suptitle("Ignition tag quality and OPC UA connection")
    save(
        fig, pdf, folder, "tag_quality_connection_vs_N", args,
        "Periodic snapshots do not establish continuous availability or "
        "data freshness. Missing tags are separate from bad-quality tags.",
    )
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    for column, label, color in [
        ("expected_tags", "Expected", COLORS[0]),
        ("missing_tags", "Missing", COLORS[1]),
        ("extra_tags", "Extra", COLORS[4]),
    ]:
        axes[0].plot(
            measured["N"], measured[f"{column}_median"],
            marker="o", label=f"{label}: median", color=color,
        )
        axes[0].plot(
            measured["N"], measured[f"{column}_max"],
            linestyle=":", label=f"{label}: maximum", color=color,
        )
    axes[0].set(ylabel="Number of tags")
    axes[0].legend(fontsize=10)
    axes[1].plot(
        measured["N"], measured["collector_ms_median"],
        marker="o", color=COLORS[1], label="Median",
    )
    axes[1].fill_between(
        measured["N"].to_numpy(), measured["collector_ms_p05"].to_numpy(),
        measured["collector_ms_p95"].to_numpy(), color=COLORS[1],
        alpha=0.15, label="P5–P95 across executions",
    )
    axes[1].set(ylabel="Diagnostic collection time per execution (ms)")
    axes[1].legend(fontsize=11)
    for ax in axes:
        ax.set_xlabel("Number of emulators, N")
        ax.set_ylim(bottom=0)
        style_axis(ax)
    fig.suptitle("Tag completeness and diagnostic script collection time")
    save(
        fig, pdf, folder, "tag_counts_collection_time_vs_N", args,
        "Collection time measures diagnostic checks inside Ignition, "
        "not sensor-to-Ignition latency. CPU-thread timing requires the "
        "separate ignition_timer_profile.csv measurements.",
    )


def tag_over_time(quality, n):
    fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    for kind, color in zip(QUALITY, QUALITY_COLORS):
        axes[0].plot(
            quality["minutes"], quality[f"{kind}_pct"],
            color=color, label=kind.capitalize(), linewidth=1,
        )
    axes[0].set(ylabel="Expected tags (%)", ylim=(-2, 105))
    axes[0].legend(ncol=4, fontsize=11)
    axes[1].plot(
        quality["minutes"], quality["collector_ms"], color=COLORS[1],
    )
    axes[1].set(
        xlabel="Minutes since start of selected window",
        ylabel="Diagnostic collection time (ms)", ylim=(0, None),
    )
    for ax in axes:
        style_axis(ax)
    fig.suptitle(f"Ignition tag diagnostics over time | N = {n}")
    return fig


def report_case(case, args):
    label, folder, color, runs, summary = case
    destination = args.output_dir
    destination.mkdir(parents=True, exist_ok=True)
    summary.to_csv(destination / "summary.csv", index=False)
    note = (
        f"{label}. All recorded resource samples. "
        "Lines: medians; bands: P5–P95 "
        "across samples, not confidence intervals. "
        "100% process CPU = one logical CPU."
    )
    with PdfPages(destination / "ignition_results.pdf") as pdf:
        series = [(label, summary, color)]
        save(resources_vs_n(series), pdf, destination, "resources_vs_N",
             args, note)
        save(cpu_spikes(series, args), pdf, destination, "cpu_spikes_vs_N",
             args, "Samples exceeding the threshold are counted individually, "
             "not as distinct peak events. 100% CPU = one logical CPU.")
        tag_plots(summary, pdf, destination, args)
        for n, (samples, quality) in sorted(runs.items()):
            save(over_time([(label, samples, color)], n), pdf, destination,
                 f"N{n}_resources_over_time", args, note)
            if not quality.empty:
                save(tag_over_time(quality, n), pdf, destination,
                     f"N{n}_tag_diagnostics", args,
                     "Tag quality is sampled periodically; good quality "
                     "alone does not prove data freshness.")
    print(f"Saved {destination / 'ignition_results.pdf'}")


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Plot one Ignition experiment without bridge inputs.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--data-dir", type=Path,
        default=ROOT / "results" / "diagnostics_disabled",
    )
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--label", help="Experiment name shown in legends")
    parser.add_argument("--devices", type=int, nargs="+")
    parser.add_argument("--spike-threshold", type=float, default=50)
    parser.add_argument("--no-images", action="store_true")
    args = parser.parse_args()
    if not math.isfinite(args.spike_threshold) or args.spike_threshold < 0:
        parser.error("--spike-threshold must be finite and nonnegative")
    if args.devices and any(n <= 0 for n in args.devices):
        parser.error("--devices must contain positive numbers")
    args.data_dir = args.data_dir.expanduser().resolve()
    args.output_dir = (
        args.output_dir.expanduser().resolve() if args.output_dir
        else ROOT / "figures" / "ignition_results" / args.data_dir.name
    )
    args.label = args.label or args.data_dir.name.replace("_", " ")
    return args


def main():
    args = parse_arguments()
    plt.rcParams.update({
        "font.size": 11, "axes.titlesize": 13,
        "axes.spines.top": False, "axes.spines.right": False,
        "legend.frameon": False,
    })
    runs, summary = load_case(args.data_dir, args)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "plot_settings.json").write_text(
        json.dumps({
            "data_dir": str(args.data_dir), "label": args.label,
            "devices": args.devices,
            "resource_window": "all samples for each N",
            "spike_threshold_percent": args.spike_threshold,
        }, indent=2) + "\n", encoding="utf-8",
    )
    report_case((args.label, args.data_dir, COLORS[0], runs, summary), args)
    print(f"Reports and summary tables: {args.output_dir}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, pd.errors.ParserError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
