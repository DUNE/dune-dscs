#!/usr/bin/env python3
"""Analyse one fixed-N endurance run without modifying its measurements."""

import argparse
import re
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages

matplotlib.use("Agg")

ROOT = Path(__file__).resolve().parents[1]
COLORS = ["#2563eb", "#d97706", "#059669"]


def read_csv(path, required, numeric):
    """Validate required columns and UTC times; preserve missing readings."""
    data = pd.read_csv(path)
    missing = set(required) - set(data.columns)
    if missing:
        raise ValueError(f"{path.name}: missing {sorted(missing)}")
    data["time_utc"] = pd.to_datetime(
        data["time_utc"], utc=True, format="ISO8601", errors="coerce",
    )
    if data["time_utc"].isna().any():
        raise ValueError(f"{path.name}: invalid timestamps")
    for column in numeric:
        if column in data:
            data[column] = pd.to_numeric(data[column], errors="coerce")
    return data.replace([np.inf, -np.inf], np.nan).sort_values("time_utc")


def read_log(path):
    """Extract controller events and error context without guessing a cause."""
    events, errors = [], []
    if not path.exists():
        return events, errors
    pattern = re.compile(r"^(\S+) \| ([\d.]+) s \| (.*)$")
    lines = path.read_text(errors="replace").splitlines()
    keep = set()
    for index, line in enumerate(lines):
        match = pattern.match(line)
        if match:
            stamp = pd.to_datetime(match[1], utc=True, errors="coerce")
            if pd.notna(stamp):
                events.append((stamp, float(match[2]), match[3]))
        if re.search(
            r"Traceback|Exception|Error:|\[!\]|Fatal|Killed", line,
            flags=re.IGNORECASE,
        ):
            keep.update(range(max(0, index - 2), min(len(lines), index + 8)))
    # Keep the final error contexts rather than copying a huge experiment log.
    for index in sorted(keep)[-100:]:
        errors.append(f"{index + 1}: {lines[index]}")
    return events, errors


def summary_rows(bridge, resources, start, end, first_good, failure):
    """Describe whole-run and health-separated windows independently."""
    windows = [("All measured cycles", start, end)]
    edge = min(pd.Timedelta(minutes=30), (end - start) / 4)
    windows += [("Initial window (up to 30 min)", start, start + edge),
                ("Final window (up to 30 min)", end - edge, end)]
    if first_good is not None and failure is not None:
        windows += [
            ("Before first unhealthy snapshot", max(start, first_good),
             failure),
            ("From first unhealthy snapshot", failure, end),
        ]
    rows = []
    for label, left, right in windows:
        for source, frame, metrics in [
            ("Bridge", bridge, ["cycle_s", "cpu_percent",
                                "cpu_active_percent", "ram_mb",
                                "acquisitions_per_s"]),
            ("Ignition", resources, ["cpu_percent", "rss_mb"]),
        ]:
            selected = frame.loc[
                frame["time_utc"].ge(left) & frame["time_utc"].lt(right)
            ]
            for metric in metrics:
                if metric not in selected:
                    continue
                values = selected[metric].dropna()
                if values.empty:
                    continue
                rows.append({
                    "window": label, "source": source, "metric": metric,
                    "samples": len(values), "mean": values.mean(),
                    "median": values.median(),
                    "p95": values.quantile(0.95), "max": values.max(),
                })
    return pd.DataFrame(rows)


def make_report(bridge, resources, tags, origin, failure, output, n):
    """Save three pages; traces retain recorded values without smoothing."""
    def hours(data):
        return (data["time_utc"] - origin).dt.total_seconds() / 3600

    def finish(fig, axes, pdf):
        for ax in axes:
            ax.set_xlabel("Hours since first measured bridge cycle")
            ax.grid(axis="y", alpha=0.2)
            ax.spines[["top", "right"]].set_visible(False)
            if failure is not None:
                ax.axvline((failure - origin).total_seconds() / 3600,
                           color="#dc2626", linestyle="--", linewidth=1,
                           label="First unhealthy tag snapshot")
            ax.legend(fontsize=9, loc="best", frameon=False)
        fig.tight_layout()
        pdf.savefig(fig)
        plt.close(fig)

    with PdfPages(output) as pdf:
        fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
        fig.suptitle(f"Endurance: bridge timing and errors | N = {n}")
        axes[0].plot(hours(bridge), bridge["cycle_s"], color=COLORS[0],
                     linewidth=0.6, label="Recorded cycle duration")
        axes[0].set_ylabel("Cycle duration (s)")
        for column, color in zip(
            ("timeouts", "send_errors", "other_errors"), COLORS,
        ):
            axes[1].plot(hours(bridge), bridge[column].cumsum(),
                         color=color, linewidth=1.4, label=column)
        axes[1].set_ylabel("Cumulative request errors")
        finish(fig, axes, pdf)

        fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
        fig.suptitle(f"Endurance: process resources | N = {n}")
        axes[0].plot(hours(bridge), bridge["cpu_percent"],
                     linewidth=0.6, color=COLORS[0],
                     label="Bridge: full-cycle CPU average")
        if "cpu_active_percent" in bridge:
            axes[0].plot(hours(bridge), bridge["cpu_active_percent"],
                         linewidth=0.6, color=COLORS[2],
                         label="Bridge: active-window CPU average")
        if not resources.empty:
            axes[0].plot(hours(resources), resources["cpu_percent"],
                         linewidth=0.5, color=COLORS[1], alpha=0.7,
                         label="Ignition: external interval CPU average")
            axes[1].plot(hours(resources), resources["rss_mb"],
                         color=COLORS[1], label="Ignition RSS")
        axes[0].set_ylabel("Process CPU (%)\n100% = one logical CPU")
        axes[1].plot(hours(bridge), bridge["ram_mb"],
                     color=COLORS[0], label="Bridge RSS")
        axes[1].set_ylabel("Resident memory (MB)")
        finish(fig, axes, pdf)

        fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
        fig.suptitle(f"Endurance: sampled Ignition tag health | N = {n}")
        for column, color in zip(
            ("good_tags", "uncertain_tags", "bad_tags"),
            (COLORS[2], COLORS[1], "#dc2626"),
        ):
            axes[0].plot(hours(tags),
                         100 * tags[column] / tags["expected_tags"],
                         color=color, linewidth=1, label=column)
        axes[0].set(ylabel="Tags (%)", ylim=(-2, 102))
        connected = tags["connection_state"].eq("CONNECTED").astype(int)
        axes[1].plot(hours(tags), connected, marker=".", markersize=2,
                     linewidth=0.6, label="Recorded connection state")
        axes[1].set_yticks([0, 1], ["Other", "Connected"])
        axes[1].set_ylim(-0.1, 1.1)
        finish(fig, axes, pdf)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    folder = args.data_dir.expanduser().resolve()
    output = (args.output_dir.expanduser().resolve() if args.output_dir
              else ROOT / "figures" / folder.name / "endurance_analysis")
    if output == folder:
        parser.error("Use a separate output directory")
    files = [p for p in folder.glob("bridge_N*.csv")
             if re.fullmatch(r"bridge_N\d+\.csv", p.name)]
    if len(files) != 1:
        parser.error("Select a single endurance folder with one bridge CSV")
    bridge_fields = ["cycle", "cycle_s", "devices", "cpu_percent", "ram_mb",
                     "attempts", "successes", "timeouts", "send_errors",
                     "other_errors"]
    bridge = read_csv(files[0], ["time_utc", *bridge_fields],
                      [*bridge_fields, "cpu_active_percent",
                       "acquisitions_per_s"])
    if bridge.empty or bridge[bridge_fields].isna().any().any():
        raise ValueError("Empty bridge CSV or invalid bridge measurements")
    if bridge["devices"].nunique() != 1 or bridge["cycle"].duplicated().any():
        raise ValueError("Expected one N and unique bridge cycle numbers")
    n = int(bridge["devices"].iloc[0])
    if bridge["cycle_s"].le(0).any():
        raise ValueError("Cycle durations must be positive")
    start = bridge["time_utc"].iloc[0] - pd.to_timedelta(
        bridge["cycle_s"].iloc[0], unit="s",
    )
    last_cycle = bridge["time_utc"].iloc[-1]
    # Half-open windows include the last saved row without boundary ambiguity.
    end = last_cycle + pd.Timedelta(nanoseconds=1)
    resources = read_csv(
        folder / "ignition_resources.csv",
        ["time_utc", "N", "pid", "cpu_percent", "rss_mb"],
        ["N", "pid", "cpu_percent", "rss_mb"],
    )
    tag_fields = ["N", "expected_tags", "missing_tags", "extra_tags",
                  "good_tags", "uncertain_tags", "bad_tags"]
    tags = read_csv(
        folder / "ignition_tag_diagnostics.csv",
        ["time_utc", "run_id", "connection_state", *tag_fields], tag_fields,
    )
    excluded_tags = int(tags["time_utc"].ge(end).sum())
    tags = tags.loc[tags["N"].eq(n) & tags["time_utc"].lt(end)].copy()
    if tags.empty or tags["run_id"].nunique() != 1:
        raise ValueError("Expected tag diagnostics for exactly one run_id")
    if tags[tag_fields].isna().any().any():
        raise ValueError("Invalid tag diagnostic counts")
    tags["connection_state"] = (
        tags["connection_state"].astype(str).str.strip().str.upper()
    )
    resources = resources.loc[
        resources["N"].eq(n) & resources["time_utc"].ge(start)
        & resources["time_utc"].lt(end)
    ].copy()
    healthy = (
        tags["good_tags"].eq(tags["expected_tags"])
        & tags["expected_tags"].eq(3 * n)
        & tags["missing_tags"].eq(0) & tags["extra_tags"].eq(0)
        & tags["uncertain_tags"].eq(0) & tags["bad_tags"].eq(0)
        & tags["connection_state"].eq("CONNECTED")
    )
    first_good = tags.loc[healthy, "time_utc"].min() if healthy.any() else None
    failures = (tags.loc[tags["time_utc"].gt(first_good) & ~healthy]
                if first_good is not None else tags.iloc[:0])
    failure = failures["time_utc"].iloc[0] if not failures.empty else None
    events, errors = read_log(folder / "experiment.log")
    lines = [f"Input: {folder}", f"Devices: {n}; expected tags: {3 * n}",
             f"Saved cycles: {len(bridge)}; last: {bridge['cycle'].max():g}",
             f"Measured window: {start} to {last_cycle}",
             f"Recorded bridge span: {last_cycle - start}",
             f"First fully healthy tag snapshot: {first_good}",
             f"First unhealthy snapshot after that: {failure}"]
    if failure is not None:
        last_good = tags.loc[
            healthy & tags["time_utc"].lt(failure), "time_utc"
        ].iloc[-1]
        lines += [f"Previous healthy snapshot: {last_good}",
                  f"First health loss lies between {last_good} and {failure}",
                  f"First Good to first unhealthy: {failure - first_good}"]
    tag_gap = tags["time_utc"].diff().dt.total_seconds().max()
    lines += [f"Largest tag snapshot gap: {tag_gap:.3f} s",
              f"Tag snapshots after last bridge row excluded: {excluded_tags}",
              "Snapshots do not prove continuous health or data freshness.",
              "Bad-tag counts alone do not identify the failure cause.",
              "Bridge CPU is per cycle; Ignition CPU is per sample interval."]
    for column in ("attempts", "successes", "timeouts", "send_errors",
                   "other_errors"):
        lines.append(f"Total {column}: {bridge[column].sum():g}")
    if bridge["attempts"].sum() > 0:
        rate = 100 * bridge["successes"].sum() / bridge["attempts"].sum()
        lines.append(f"Request success percentage: {rate:.6f}%")
    if resources["pid"].nunique() > 1:
        lines.append("WARNING: multiple monitored JVM PIDs in this window.")
    settings_path = folder / "test_settings.json"
    if settings_path.exists():
        lines += ["", "Saved settings:", settings_path.read_text()]
    lines += ["", "Controller events (not an inferred failure cause):"]
    lines += [f"{stamp} | {seconds:.1f} s | {message}"
              for stamp, seconds, message in events]
    lines += ["", "Last error contexts from experiment.log:"] + errors
    summary = summary_rows(bridge, resources, start, end, first_good, failure)
    output.mkdir(parents=True, exist_ok=True)
    summary.to_csv(output / "endurance_summary.csv", index=False)
    (output / "endurance_summary.txt").write_text(
        "\n".join(lines) + "\n\n" + summary.round(3).to_string(index=False)
        + "\n", encoding="utf-8",
    )
    make_report(bridge, resources, tags, start, failure,
                output / "endurance_report.pdf", n)
    print("\n".join(lines[:18]))
    print(f"\nSaved three report files in {output}")


if __name__ == "__main__":
    main()
