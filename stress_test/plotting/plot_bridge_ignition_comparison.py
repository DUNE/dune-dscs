#!/usr/bin/env python3
"""Compare bridge and Ignition CPU and resident memory from selected folders.

Use bridge_N<number>.csv for bridge measurements and
ignition_resources.csv for Ignition measurements. All Ignition resource
samples for each N are used. Individual runs need not have the same N set.
"""

import argparse
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages

from plot_bridge_results import (
    BLUE, ORANGE, ROOT, load_bridge_data, save_plot, style_axis,
    summarize_metrics,
)


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bridge-dir", type=Path, required=True)
    parser.add_argument("--ignition-dir", type=Path, required=True)
    parser.add_argument(
        "--output-dir", type=Path,
        default=ROOT / "figures" / "bridge_ignition_comparison",
    )
    parser.add_argument("--devices", type=int, nargs="+")
    parser.add_argument("--no-images", action="store_true")
    args = parser.parse_args()
    args.bridge_dir = args.bridge_dir.expanduser().resolve()
    args.ignition_dir = args.ignition_dir.expanduser().resolve()
    args.output_dir = args.output_dir.expanduser().resolve()
    if args.devices and any(n <= 0 for n in args.devices):
        parser.error("--devices must contain positive numbers")
    datasets = load_bridge_data(args.bridge_dir, 0, args.devices)
    bridge = summarize_metrics(datasets)
    bridge = bridge.loc[bridge["metric"].isin(["cpu_percent", "ram_mb"])]
    ignition = load_ignition_resources(args.ignition_dir, args.devices)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    pd.concat([
        bridge.assign(component="Bridge"),
        ignition.assign(component="Ignition"),
    ], ignore_index=True).to_csv(
        args.output_dir / "resource_summary.csv", index=False,
    )
    (args.output_dir / "plot_settings.json").write_text(
        json.dumps({
            "bridge_dir": str(args.bridge_dir),
            "ignition_dir": str(args.ignition_dir),
            "devices": args.devices,
            "resource_window": "all recorded samples for each N",
        }, indent=2) + "\n", encoding="utf-8",
    )
    plt.rcParams.update({
        "font.size": 11, "axes.spines.top": False,
        "axes.spines.right": False, "legend.frameon": False,
    })
    path = args.output_dir / "bridge_ignition_comparison.pdf"
    with PdfPages(path) as pdf:
        plot_resource_comparisons([
            ("Bridge", bridge, BLUE), ("Ignition", ignition, ORANGE),
        ], pdf, args)
    print(f"Saved {path}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, pd.errors.ParserError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
