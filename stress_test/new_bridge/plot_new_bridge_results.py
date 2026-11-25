#!/usr/bin/env python3
"""Plot new-bridge diagnostics versus N (adapted plotting/plot_bridge_results.py).

Run from stress_test with the plotting environment:
    ~/DSCS/opcua-env/bin/python new_bridge/plot_new_bridge_results.py \
        --data-dir results/new_bridge_scaling [--compare-dir results/bridge_only]

Inputs are bridge_N<number>.csv files written by new_bridge/bridge_diagnostic.py
(one row per measurement window). --compare-dir overlays an old-bridge
experiment (one row per polling cycle) where the quantity is comparable.
Reports go to figures/<data-dir name>/ and are overwritten on re-runs.
"""

import argparse
import json
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
BLUE, ORANGE, GREEN, PURPLE, GREY = "#2563eb", "#d97706", "#059669", "#9333ea", "#6b7280"

# metric: (title, y label). Each is summarised across windows for every N.
METRICS = {
    "window_s": ("Measurement-window duration", "Window duration (s)"),
    "cpu_percent": ("Bridge CPU usage", "Process CPU usage (%)"),
    "ram_mb": ("Bridge resident memory", "Resident memory (MB)"),
    "threads": ("Bridge threads", "Threads"),
    "file_descriptors": ("Bridge open file descriptors", "File descriptors"),
    "acquisitions_per_s": ("Successful device acquisitions per window", "Acquisitions/s — all devices"),
    "node_writes_per_s": ("Good-quality variable writes per window", "Writes/s — all variables"),
    "failure_percent": ("Device-poll failure percentage per window", "Failed polls (%)"),
    "timeouts": ("Device-read timeouts per window", "Timeout count"),
    "comm_errors": ("Communication errors per window", "Error count"),
    "decode_errors": ("Decoding/conversion errors per window", "Error count"),
    "mean_request_ms": ("Mean ZMQ request latency per window", "Request duration (ms)"),
    "request_median_ms": ("Median ZMQ request latency per window", "Request duration (ms)"),
    "request_p95_ms": ("ZMQ request latency P95 per window", "Request duration (ms)"),
    "request_p99_ms": ("ZMQ request latency P99 per window", "Request duration (ms)"),
    "query_median_ms": ("Median complete device read per window", "Device read (ms)"),
    "query_p95_ms": ("Complete device read P95 per window", "Device read (ms)"),
    "query_p99_ms": ("Complete device read P99 per window", "Device read (ms)"),
    "publish_total_ms": ("Total OPC UA publish time per window", "Publish duration (ms)"),
    "zmq_tx_payload_kB_s": ("Transmitted ZMQ payload throughput", "Payload (kB/s)"),
    "zmq_rx_payload_kB_s": ("Received ZMQ payload throughput", "Payload (kB/s)"),
    "queue_p95_ms": ("Wait for a concurrency slot, P95 per window", "Queue time (ms)"),
    "lateness_p95_ms": ("Poll start lateness, P95 per window", "Lateness (ms)"),
    "lateness_max_ms": ("Poll start lateness, maximum per window", "Lateness (ms)"),
    "overruns": ("Polls longer than the period, per window", "Overrun count"),
    "devices_stale": ("Devices without a good value for > 2 periods", "Stale devices"),
    "max_value_age_s": ("Oldest good value at window end", "Value age (s)"),
    "loop_lag_max_ms": ("Event-loop lag, maximum per window", "Lag (ms)"),
}
# New metric -> old CSV column with the same meaning (for --compare-dir).
COMPARABLE = {
    "cpu_percent": "cpu_percent", "ram_mb": "ram_mb",
    "mean_request_ms": "mean_request_ms", "request_median_ms": "request_median_ms",
    "request_p95_ms": "request_p95_ms", "request_p99_ms": "request_p99_ms",
    "failure_percent": "failure_percent",
}


def style_axis(ax, versus_n=False):
    ax.grid(axis="y", alpha=0.2)
    ax.set_axisbelow(True)
    if versus_n:
        ax.set_xlabel("Number of configured devices, N")
        ax.set_xlim(left=0)


def add_line(ax, x, y, label, color, linestyle="-"):
    values = np.asarray(y, dtype=float)
    if np.isfinite(values).any():
        ax.plot(x, values, color=color, marker="o", markersize=4, linewidth=1.7,
                linestyle=linestyle, label=label)


def add_legend(ax):
    if ax.get_legend_handles_labels()[0]:
        ax.legend(fontsize=10)


def median_band(ax, summary, metric, color=BLUE, label="New bridge"):
    unit = "cycles" if label.startswith("Old") else "windows"
    selected = summary[summary["metric"] == metric].sort_values("N")
    if selected.empty:
        return selected
    ax.fill_between(selected["N"].to_numpy(), selected["p05"].to_numpy(), selected["p95"].to_numpy(),
                    color=color, alpha=0.16, label=f"{label}: P5–P95 across {unit}")
    add_line(ax, selected["N"], selected["median"], f"{label}: median across {unit}", color)
    return selected


def save_plot(fig, name, pdf, args, note=None):
    if note:
        fig.text(0.5, 0.01, textwrap.fill(note, width=115), ha="center", va="bottom", fontsize=9)
    fig.tight_layout(rect=(0, 0.12 if note else 0, 1, 1))
    pdf.savefig(fig)
    if not args.no_images:
        fig.savefig(args.output_dir / f"{name}.png", dpi=200)
    plt.close(fig)


def load(data_dir, time_column, skip, selected):
    """One bridge_N<N>.csv per N; works for new (window) and old (cycle) files."""
    pattern = re.compile(r"bridge_N(\d+)\.csv")
    datasets = []
    for file in sorted(data_dir.glob("bridge_N*.csv")):
        match = pattern.fullmatch(file.name)
        if match is None or (selected and int(match.group(1)) not in selected):
            continue
        try:
            data = pd.read_csv(file)
        except pd.errors.EmptyDataError:
            print(f"Skipping empty file: {file.name}")
            continue
        index = "window" if "window" in data else "cycle"
        if time_column not in data or index not in data:
            print(f"Skipping {file.name}: not a {time_column} file")
            continue
        for column in data.columns:
            if column not in {"time_utc", "error_types"}:
                data[column] = pd.to_numeric(data[column], errors="coerce")
        data = data.replace([np.inf, -np.inf], np.nan)
        raw = len(data)
        data = data[(data[time_column] > 0) & (data[index] > skip)].sort_values(index)
        if data.empty:
            print(f"No usable rows: {file.name}")
            continue
        n = int(match.group(1))
        if not data["devices"].eq(n).all():
            raise ValueError(f"{file.name}: filename and recorded N disagree")
        settings_file = file.with_name(f"bridge_N{n}_settings.json")
        settings = json.loads(settings_file.read_text()) if settings_file.exists() else {}
        datasets.append({"file": file, "N": n, "data": data, "raw": raw, "index": index,
                         "settings": settings})
    datasets.sort(key=lambda item: item["N"])
    return datasets


def summarize(datasets, metrics):
    rows = []
    for item in datasets:
        for metric in metrics:
            if metric not in item["data"]:
                continue
            values = item["data"][metric].dropna()
            if values.empty:
                continue
            rows.append({"file": item["file"].name, "N": item["N"], "metric": metric,
                         "samples": len(values), "mean": values.mean(), "std": values.std(),
                         "minimum": values.min(), "p05": values.quantile(0.05),
                         "median": values.median(), "p95": values.quantile(0.95),
                         "p99": values.quantile(0.99), "maximum": values.max()})
    return pd.DataFrame(rows, columns=["file", "N", "metric", "samples", "mean", "std", "minimum",
                                       "p05", "median", "p95", "p99", "maximum"])


def run_totals(datasets):
    """Whole-run rates and failure fractions from summed counts and time."""
    rows = []
    for item in datasets:
        data, settings = item["data"], item["settings"]
        seconds = data["window_s"].sum()
        polls = data["polls"].sum()
        period = settings.get("period_s")
        nvars = settings.get("variables_per_device")
        row = {"file": item["file"].name, "N": item["N"], "windows": len(data), "measured_s": seconds,
               "polls": polls, "successes": data["successes"].sum(),
               "acquisitions_per_s": data["successes"].sum() / seconds,
               "node_writes_per_s": data["node_writes"].sum() / seconds,
               "expected_acquisitions_per_s": item["N"] / period if period else np.nan,
               "expected_node_writes_per_s": item["N"] * nvars / period if period and nvars else np.nan,
               "tx_payload_kB_s": (data["zmq_tx_payload_kB_s"] * data["window_s"]).sum() / seconds,
               "rx_payload_kB_s": (data["zmq_rx_payload_kB_s"] * data["window_s"]).sum() / seconds,
               "overruns_total": data["overruns"].sum(),
               "max_lateness_ms": data["lateness_max_ms"].max(),
               "max_value_age_s": data["max_value_age_s"].max()}
        for column in ("timeouts", "comm_errors", "decode_errors"):
            row[f"{column}_total"] = data[column].sum()
            row[f"{column}_percent"] = 100 * data[column].sum() / polls if polls else np.nan
        row["failure_percent"] = sum(row[f"{c}_percent"] for c in ("timeouts", "comm_errors", "decode_errors"))
        rows.append(row)
    return pd.DataFrame(rows).sort_values("N")


def old_failure_totals(datasets):
    rows = []
    for item in datasets:
        data = item["data"]
        needed = ["attempts", "timeouts", "send_errors", "other_errors"]
        if set(needed).issubset(data) and data["attempts"].sum() > 0:
            failures = data[["timeouts", "send_errors", "other_errors"]].sum().sum()
            rows.append({"N": item["N"], "failure_percent": 100 * failures / data["attempts"].sum()})
    return pd.DataFrame(rows, columns=["N", "failure_percent"])


def setting_text(datasets):
    settings = datasets[0]["settings"]
    if not settings:
        return ""
    return (f"Period {settings.get('period_s')} s, timeout {settings.get('timeout_s')} s, "
            f"concurrency {settings.get('concurrency')}, {settings.get('variables_per_device')} variables/device, "
            f"window {settings.get('window_s')} s.")


def plot_all(datasets, summary, runs, old_summary, old_runs, args):
    base_note = "Bands show variation across windows, not confidence intervals. " + setting_text(datasets)
    with PdfPages(args.output_dir / "bridge_results.pdf") as pdf:
        # Each metric versus N, with the old bridge overlaid where comparable.
        for metric, (title, ylabel) in METRICS.items():
            if metric not in set(summary["metric"]):
                continue
            fig, ax = plt.subplots(figsize=(9, 5))
            median_band(ax, summary, metric)
            note = base_note
            if old_summary is not None and metric in COMPARABLE:
                median_band(ax, old_summary, COMPARABLE[metric], ORANGE, "Old bridge")
                note += " Old bridge: per polling cycle."
            if metric == "cpu_percent":
                note += " 100% CPU = one logical CPU. No 'excluding sleep' variant: the new bridge has no global sleep."
            ax.set_title(title)
            ax.set_ylabel(ylabel)
            style_axis(ax, versus_n=True)
            add_legend(ax)
            save_plot(fig, f"{metric}_vs_N", pdf, args, note)

        # Resources.
        fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
        for ax, metric, title, ylabel in [(axes[0], "cpu_percent", "Bridge CPU", "Process CPU (%)"),
                                          (axes[1], "ram_mb", "Bridge memory", "Resident memory (MB)")]:
            median_band(ax, summary, metric)
            if old_summary is not None:
                median_band(ax, old_summary, metric, ORANGE, "Old bridge")
            ax.set_title(title)
            ax.set_ylabel(ylabel)
            style_axis(ax, versus_n=True)
            add_legend(ax)
        save_plot(fig, "resources_vs_N", pdf, args, "P5–P95 describes windows. 100% CPU = one logical CPU.")

        # ZMQ request latency (same definition as the old 'request').
        fig, ax = plt.subplots(figsize=(9, 5))
        for metric, label, color in [("request_median_ms", "Window request median", BLUE),
                                     ("request_p95_ms", "Window request P95", GREEN),
                                     ("request_p99_ms", "Window request P99", ORANGE)]:
            selected = summary[summary["metric"] == metric]
            add_line(ax, selected["N"], selected["median"], label, color)
            if old_summary is not None:
                old = old_summary[old_summary["metric"] == metric]
                add_line(ax, old["N"], old["median"], f"Old: {label.split(' ', 1)[1]}", color, "--")
        ax.set_title("ZMQ request latency versus device count")
        ax.set_ylabel("Request–response duration (ms)")
        style_axis(ax, versus_n=True)
        add_legend(ax)
        save_plot(fig, "request_latency_combined_vs_N", pdf, args,
                  "One request = one ZMQ round trip (new bridge: 4 per device poll). Lines are medians across "
                  "windows of each window's statistic. Successful requests only.")

        # Complete device read.
        fig, ax = plt.subplots(figsize=(9, 5))
        for metric, label, color in [("query_median_ms", "Median", BLUE), ("query_p95_ms", "P95", GREEN),
                                     ("query_p99_ms", "P99", ORANGE)]:
            selected = summary[summary["metric"] == metric]
            add_line(ax, selected["N"], selected["median"], label, color)
        timeout = datasets[0]["settings"].get("timeout_s")
        if timeout:
            ax.axhline(timeout * 1000, color=GREY, linestyle=":", label=f"Timeout ({timeout} s)")
        ax.set_title("Complete device read versus device count")
        ax.set_ylabel("Device read duration (ms)")
        style_axis(ax, versus_n=True)
        add_legend(ax)
        save_plot(fig, "device_read_latency_vs_N", pdf, args,
                  "Bridge query_ms: all protobuf groups of one device, including failed reads.")

        # Scheduling health (new: replaces the growing old cycle duration).
        fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
        for metric, label, color in [("queue_p95_ms", "Queue wait P95", BLUE),
                                     ("lateness_p95_ms", "Start lateness P95", GREEN),
                                     ("lateness_max_ms", "Start lateness max", ORANGE)]:
            selected = summary[summary["metric"] == metric]
            add_line(axes[0], selected["N"], selected["median"], label, color)
        axes[0].set_title("Polling delays")
        axes[0].set_ylabel("Median across windows (ms)")
        for metric, label, color in [("overruns", "Overrun polls", BLUE),
                                     ("devices_stale", "Stale devices", ORANGE)]:
            selected = summary[summary["metric"] == metric]
            add_line(axes[1], selected["N"], selected["maximum"], label, color)
        axes[1].set_title("Overload indicators")
        axes[1].set_ylabel("Maximum per window")
        axes[1].yaxis.set_major_locator(MaxNLocator(integer=True))
        for ax in axes:
            style_axis(ax, versus_n=True)
            add_legend(ax)
        save_plot(fig, "scheduling_vs_N", pdf, args,
                  "The new bridge has no polling cycle: overload shows as queue wait, late poll starts, polls "
                  "longer than the period and devices whose last good value is older than two periods.")

        # Reliability.
        fig, ax = plt.subplots(figsize=(9, 5))
        for column, label, color in [("failure_percent", "All poll failures", BLUE),
                                     ("timeouts_percent", "Timeouts", ORANGE),
                                     ("comm_errors_percent", "Communication errors", GREEN),
                                     ("decode_errors_percent", "Decoding errors", PURPLE)]:
            add_line(ax, runs["N"], runs[column], label, color)
        if old_runs is not None and not old_runs.empty:
            add_line(ax, old_runs["N"], old_runs["failure_percent"], "Old bridge: all request failures",
                     GREY, "--")
        ax.set_title("Failures versus device count")
        ax.set_ylabel("Failed / attempted polls (%)")
        ax.set_ylim(bottom=0)
        style_axis(ax, versus_n=True)
        add_legend(ax)
        save_plot(fig, "request_failures_total_vs_N", pdf, args,
                  "Calculated from summed counts. New: one poll = one complete device read.")

        # Payload throughput.
        fig, ax = plt.subplots(figsize=(9, 5))
        add_line(ax, runs["N"], runs["tx_payload_kB_s"], "Bridge to emulators", BLUE)
        add_line(ax, runs["N"], runs["rx_payload_kB_s"], "Emulators to bridge", ORANGE)
        ax.set_title("ZMQ payload throughput versus device count")
        ax.set_ylabel("Payload throughput (kB/s)")
        ax.set_ylim(bottom=0)
        style_axis(ax, versus_n=True)
        add_legend(ax)
        save_plot(fig, "zmq_payload_combined_vs_N", pdf, args,
                  "Time-weighted payload throughput. Excludes protocol overhead.")

        # Rates, with the ideal N/period line.
        fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
        for ax, column, expected, title, ylabel in [
                (axes[0], "acquisitions_per_s", "expected_acquisitions_per_s",
                 "Successful device acquisitions", "Acquisitions/s — all devices"),
                (axes[1], "node_writes_per_s", "expected_node_writes_per_s",
                 "Good-quality variable writes", "Writes/s — all variables")]:
            add_line(ax, runs["N"], runs[column], "Measured", BLUE)
            add_line(ax, runs["N"], runs[expected], "Ideal: N / period", GREY, "--")
            ax.set_title(title)
            ax.set_ylabel(ylabel)
            ax.set_ylim(bottom=0)
            style_axis(ax, versus_n=True)
            add_legend(ax)
        save_plot(fig, "operation_rates_total_vs_N", pdf, args,
                  "Successful operations divided by measured time. Falling below the ideal line means "
                  "the bridge cannot keep the configured period.")

        # Processing time.
        fig, ax = plt.subplots(figsize=(9, 5))
        selected = summary[summary["metric"] == "publish_total_ms"]
        add_line(ax, selected["N"], selected["median"], "OPC UA publish (all devices)", ORANGE)
        if old_summary is not None:
            old = old_summary[old_summary["metric"] == "update_total_ms"]
            add_line(ax, old["N"], old["median"], "Old bridge: OPC UA node updates", ORANGE, "--")
        ax.set_title("Bridge processing time versus device count")
        ax.set_ylabel("Median total duration per window (ms)")
        style_axis(ax, versus_n=True)
        add_legend(ax)
        save_plot(fig, "processing_combined_vs_N", pdf, args,
                  "Response parsing is not separable in the new bridge: it is inside the device read. "
                  "Publish also writes Available/LastError/LastSuccess/Sequence status nodes.")

        # Errors, compact.
        fig, axes = plt.subplots(1, 3, figsize=(11, 3.2), sharey=True)
        columns = ["timeouts_total", "comm_errors_total", "decode_errors_total"]
        maximum = runs[columns].max().max()
        for ax, column, title in zip(axes, columns, ["Timeouts", "Communication errors", "Decoding errors"]):
            add_line(ax, runs["N"], runs[column], title, BLUE)
            ax.set_title(title)
            ax.yaxis.set_major_locator(MaxNLocator(integer=True))
            style_axis(ax, versus_n=True)
            if runs[column].fillna(0).eq(0).all():
                ax.text(0.5, 0.55, "0 recorded", transform=ax.transAxes, ha="center",
                        fontsize=15, fontweight="bold")
        axes[0].set_ylim(-0.05, max(1, maximum if pd.notna(maximum) else 1) * 1.15)
        axes[0].set_ylabel("Total events per run")
        save_plot(fig, "bridge_errors_vs_N_compact", pdf, args, "Totals over analysed windows for each N.")

        # Per-N time series.
        for item in datasets if args.extra_diagnostic_pictures else []:
            data = item["data"]
            fig, axes = plt.subplots(3, 1, figsize=(9, 8), sharex=True)
            axes[0].plot(data["window"], data["acquisitions_per_s"], color=BLUE)
            axes[0].set_ylabel("Acquisitions/s")
            axes[1].plot(data["window"], data["lateness_max_ms"], color=ORANGE, label="Lateness max")
            axes[1].plot(data["window"], data["query_p95_ms"], color=GREEN, label="Device read P95")
            axes[1].set_ylabel("ms")
            add_legend(axes[1])
            axes[2].plot(data["window"], data["cpu_percent"], color=PURPLE)
            axes[2].set_ylabel("CPU (%)")
            axes[2].set_xlabel("Measurement window")
            axes[0].set_title(f"New bridge time series | N = {item['N']}")
            for ax in axes:
                style_axis(ax)
            save_plot(fig, f"{item['file'].stem}_timeseries", pdf, args)


def parse_arguments():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "results" / "new_bridge_scaling")
    parser.add_argument("--compare-dir", type=Path, help="old-bridge experiment folder to overlay")
    parser.add_argument("--output-dir", type=Path, help="default: figures/<data-dir name>")
    parser.add_argument("--devices", type=int, nargs="+", help="only these N")
    parser.add_argument("--skip-windows", type=int, default=0, help="drop windows <= this number")
    parser.add_argument("--no-images", action="store_true", help="PDF only, no PNGs")
    parser.add_argument("--extra-diagnostic-pictures", action="store_true", help="per-N time series")
    args = parser.parse_args()
    args.data_dir = args.data_dir.expanduser().resolve()
    if not args.data_dir.is_dir():
        parser.error(f"Data directory does not exist: {args.data_dir}")
    if args.compare_dir is not None:
        args.compare_dir = args.compare_dir.expanduser().resolve()
        if not args.compare_dir.is_dir():
            parser.error(f"Comparison directory does not exist: {args.compare_dir}")
    args.output_dir = (args.output_dir.expanduser().resolve() if args.output_dir
                       else ROOT / "figures" / args.data_dir.name)
    return args


def main():
    args = parse_arguments()
    datasets = load(args.data_dir, "window_s", args.skip_windows, args.devices)
    if not datasets:
        raise ValueError(f"No usable new-bridge bridge_N<number>.csv files in {args.data_dir}")
    print("Files used:")
    for item in datasets:
        print(f"  {item['file'].name}: N={item['N']}, {len(item['data'])} windows")
    old_summary = old_runs = None
    if args.compare_dir:
        old = load(args.compare_dir, "cycle_s", 0, args.devices)
        if not old:
            raise ValueError(f"No old-bridge bridge_N<number>.csv files in {args.compare_dir}")
        print(f"Comparison: {len(old)} old-bridge files from {args.compare_dir}")
        old_summary = summarize(old, set(COMPARABLE.values()) | {"update_total_ms"})
        old_runs = old_failure_totals(old)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.size": 11, "axes.titlesize": 14, "axes.spines.top": False,
                         "axes.spines.right": False, "legend.frameon": False})
    summary = summarize(datasets, METRICS)
    runs = run_totals(datasets)
    summary.to_csv(args.output_dir / "bridge_summary.csv", index=False)
    runs.to_csv(args.output_dir / "bridge_run_totals.csv", index=False)
    pd.DataFrame([{"source_file": str(i["file"]), "N": i["N"], "raw_windows": i["raw"],
                   "analysed_windows": len(i["data"])} for i in datasets]).to_csv(
        args.output_dir / "input_files.csv", index=False)
    (args.output_dir / "plot_settings.json").write_text(json.dumps(
        {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()}, indent=2) + "\n")
    plot_all(datasets, summary, runs, old_summary, old_runs, args)
    print(f"Reports saved in {args.output_dir} (bridge_results.pdf, PNGs, CSV summaries)")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, pd.errors.ParserError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
