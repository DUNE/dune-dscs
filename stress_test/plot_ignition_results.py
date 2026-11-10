from pathlib import Path
import re

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import numpy as np
import pandas as pd


BASE = Path(__file__).resolve().parent
OUTPUT = BASE / "ignition_timer_plots"

CASES = {
    "enabled": (BASE / "timer_enabled_case", "Timer enabled", "#d97706"),
    "disabled": (BASE / "timer_disabled_case", "Timer disabled", "#2563eb"),
}

METRICS = {
    "cpu_percent": "Gateway CPU (%)",
    "rss_mb": "Gateway RAM (MB)",
}
QUALITY = ("good", "uncertain", "bad", "missing")
SPIKE_THRESHOLD = 50

plt.rcParams.update({
    "font.size": 11,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "legend.frameon": False,
})


def read_csv(path, numeric_columns):
    data = pd.read_csv(path)
    data["time_utc"] = pd.to_datetime(
        data["time_utc"], utc=True, format="ISO8601", errors="coerce"
    )
    for column in numeric_columns:
        data[column] = pd.to_numeric(data[column], errors="coerce")

    clean = data.replace([np.inf, -np.inf], np.nan).dropna(
        subset=["time_utc", *numeric_columns]
    )
    if len(clean) != len(data):
        print(f"{path.name}: excluded {len(data) - len(clean)} invalid rows")

    return clean.sort_values("time_utc")


def load_case(folder):
    resources = read_csv(
        folder / "ignition_resources.csv", ["N", *METRICS]
    )

    tags = None
    tag_file = folder / "ignition_tag_diagnostics.csv"
    if tag_file.is_file():
        counts = [f"{kind}_tags" for kind in QUALITY]
        tags = read_csv(
            tag_file,
            ["N", "expected_tags", "extra_tags", "collector_ms", *counts],
        )
        tags = tags.loc[
            tags.expected_tags.gt(0)
            & tags.expected_tags.eq(3 * tags.N)
            & tags[counts + ["extra_tags"]].ge(0).all(axis=1)
            & tags[counts].sum(axis=1).eq(tags.expected_tags)
        ].copy()
        for kind in QUALITY:
            tags[f"{kind}_pct"] = (
                100 * tags[f"{kind}_tags"] / tags.expected_tags
            )

    runs = {}
    rows = []

    for path in folder.glob("bridge_N*.csv"):
        match = re.fullmatch(r"bridge_N(\d+)\.csv", path.name)
        if match is None:
            continue  # Ignore _1 and other suffixed files.

        n = int(match.group(1))
        bridge = read_csv(path, ["devices", "cycle_s"])
        if bridge.empty:
            print(f"{path}: no measured cycles")
            continue
        if not bridge.devices.eq(n).all() or not bridge.cycle_s.gt(0).all():
            raise ValueError(f"{path}: invalid device count or cycle duration")

        first = bridge.iloc[0]
        start = first.time_utc - pd.to_timedelta(first.cycle_s, unit="s")
        end = bridge.iloc[-1].time_utc

        samples = resources.loc[
            resources.N.eq(n) & resources.time_utc.between(start, end)
        ].copy()
        if samples.empty:
            print(f"{path}: no matching Ignition resource samples")
            continue

        samples["minutes"] = (samples.time_utc - start).dt.total_seconds() / 60

        row = {
            "N": n,
            "start_utc": start.isoformat(),
            "end_utc": end.isoformat(),
            "resource_samples": len(samples),
            "bridge_cycles": len(bridge),
            "bridge_cycle_median_s": bridge.cycle_s.median(),
            "cpu_above_threshold_pct": (
                100 * samples.cpu_percent.gt(SPIKE_THRESHOLD).mean()
            ),
        }
        for metric in METRICS:
            values = samples[metric]
            row.update({
                f"{metric}_mean": values.mean(),
                f"{metric}_median": values.median(),
                f"{metric}_p05": values.quantile(0.05),
                f"{metric}_p95": values.quantile(0.95),
                f"{metric}_max": values.max(),
            })

        quality = pd.DataFrame()
        if tags is not None:
            quality = tags.loc[
                tags.N.eq(n) & tags.time_utc.between(start, end)
            ].copy()

        if not quality.empty:
            quality["minutes"] = (
                quality.time_utc - start
            ).dt.total_seconds() / 60
            row["tag_samples"] = len(quality)
            for kind in QUALITY:
                row[f"{kind}_tag_pct"] = quality[f"{kind}_pct"].mean()
            row["all_good_samples_pct"] = 100 * (
                quality.good_tags.eq(quality.expected_tags)
                & quality.extra_tags.eq(0)
            ).mean()
            row["collector_p95_ms"] = quality.collector_ms.quantile(0.95)
            row["connected_samples_pct"] = 100 * (
                quality.connection_state.str.strip().str.upper().eq("CONNECTED")
            ).mean()

        runs[n] = (samples, quality)
        rows.append(row)

    if not rows:
        raise ValueError(f"{folder}: no matching bridge and Ignition measurements")

    summary = pd.DataFrame(rows).sort_values("N")
    print(f"{folder.name}: N = {summary.N.tolist()}")
    return runs, summary


def save(fig, pdf, folder, name):
    fig.tight_layout()
    pdf.savefig(fig, bbox_inches="tight")
    fig.savefig(folder / f"{name}.png", dpi=250, bbox_inches="tight")
    plt.close(fig)


def resources_vs_n(series, title):
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))

    for ax, (metric, ylabel) in zip(axes, METRICS.items()):
        for label, summary, color in series:
            x = summary.N.to_numpy()
            ax.plot(
                x, summary[f"{metric}_median"].to_numpy(),
                color=color, marker="o", label=label,
            )
            ax.fill_between(
                x,
                summary[f"{metric}_p05"].to_numpy(),
                summary[f"{metric}_p95"].to_numpy(),
                color=color, alpha=0.15,
            )
        ax.set(xlabel="Number of emulators, N", ylabel=ylabel)
        ax.grid(axis="y", alpha=0.2)
        ax.legend()

    fig.suptitle(
        title + "\nMedian and P5–P95 across samples"
    )
    return fig


def over_time(series, n, quality=None):
    has_quality = quality is not None and not quality.empty
    fig, axes = plt.subplots(
        3 if has_quality else 2, 1,
        figsize=(10, 8 if has_quality else 6), sharex=True,
    )

    for ax, (metric, ylabel) in zip(axes, METRICS.items()):
        for label, samples, color in series:
            ax.plot(
                samples.minutes, samples[metric],
                color=color, linewidth=0.9, alpha=0.85, label=label,
            )
        ax.set_ylabel(ylabel)
        ax.ticklabel_format(axis="y", style="plain", useOffset=False)
        ax.legend()

    if has_quality:
        for kind in QUALITY:
            axes[2].plot(
                quality.minutes, quality[f"{kind}_pct"],
                marker=".", label=kind.capitalize(),
            )
        axes[2].set(ylabel="Expected tags (%)", ylim=(0, 102))
        axes[2].legend(ncol=4)

    for ax in axes:
        ax.grid(axis="y", alpha=0.2)

    axes[-1].set_xlabel("Minutes since start of each measured window")
    fig.suptitle(f"N = {n}")
    return fig


def tag_plots(summary, pdf, folder):
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))

    for column, label in [
        ("good_tag_pct", "Mean good tag share"),
        ("all_good_samples_pct", "Snapshots with all expected tags good"),
    ]:
        axes[0, 0].plot(summary.N, summary[column], marker="o", label=label)
    axes[0, 0].set(ylabel="Percent (%)", ylim=(0, 102))
    axes[0, 0].legend(fontsize=9)

    for kind in ("uncertain", "bad", "missing"):
        axes[0, 1].plot(
            summary.N, summary[f"{kind}_tag_pct"],
            marker="o", label=kind.capitalize(),
        )
    axes[0, 1].set(ylabel="Mean share of expected tags (%)", ylim=(0, None))
    axes[0, 1].legend()

    axes[1, 0].plot(summary.N, summary.connected_samples_pct, marker="o")
    axes[1, 0].set(ylabel="Snapshots reporting CONNECTED (%)", ylim=(0, 102))

    axes[1, 1].plot(summary.N, summary.collector_p95_ms, marker="o")
    axes[1, 1].set(ylabel="Collector P95 duration (ms)")

    for ax in axes.flat:
        ax.set_xlabel("Number of emulators, N")
        ax.grid(axis="y", alpha=0.2)

    fig.suptitle("Ignition tag diagnostics · periodic snapshots")
    save(fig, pdf, folder, "tag_diagnostics_vs_N")


def main():
    results = {}
    for state, (folder, label, color) in CASES.items():
        runs, summary = load_case(folder)
        results[state] = (runs, summary)

        destination = OUTPUT / state
        destination.mkdir(parents=True, exist_ok=True)
        summary.to_csv(destination / "summary.csv", index=False)

        with PdfPages(destination / f"ignition_timer_{state}.pdf") as pdf:
            save(
                resources_vs_n([(label, summary, color)], label),
                pdf, destination, "resources_vs_N",
            )
            if "tag_samples" in summary:
                tag_plots(summary, pdf, destination)
            for n, (samples, quality) in sorted(runs.items()):
                save(
                    over_time([(label, samples, color)], n, quality),
                    pdf, destination, f"N{n}_over_time",
                )

    enabled, enabled_summary = results["enabled"]
    disabled, disabled_summary = results["disabled"]
    common = sorted(set(enabled) & set(disabled))
    if not common:
        print("Separate reports saved. No matching N values for comparison.")
        return

    destination = OUTPUT / "comparison"
    destination.mkdir(parents=True, exist_ok=True)

    enabled_summary = enabled_summary.loc[enabled_summary.N.isin(common)]
    disabled_summary = disabled_summary.loc[disabled_summary.N.isin(common)]
    enabled_summary.merge(
        disabled_summary, on="N", suffixes=("_enabled", "_disabled")
    ).to_csv(destination / "summary.csv", index=False)

    _, on_label, on_color = CASES["enabled"]
    _, off_label, off_color = CASES["disabled"]
    series = [
        (on_label, enabled_summary, on_color),
        (off_label, disabled_summary, off_color),
    ]

    with PdfPages(destination / "ignition_timer_comparison.pdf") as pdf:
        save(
            resources_vs_n(series, "Ignition timer comparison"),
            pdf, destination, "resources_vs_N",
        )

        fig, axes = plt.subplots(1, 3, figsize=(14, 4.5))
        for ax, column, ylabel in [
            (axes[0], "cpu_percent_mean", "Mean Gateway CPU (%)"),
            (axes[1], "cpu_percent_p95", "Gateway CPU P95 (%)"),
            (axes[2], "cpu_above_threshold_pct",
             f"Samples above {SPIKE_THRESHOLD}% CPU (%)"),
        ]:
            for label, summary, color in series:
                ax.plot(summary.N, summary[column], marker="o", color=color, label=label)
            ax.set(xlabel="Number of emulators, N", ylabel=ylabel, ylim=(0, None))
            ax.grid(axis="y", alpha=0.2)
            ax.legend()

        #fig.suptitle("Ignition CPU usage and spikes by timer state")
        save(fig, pdf, destination, "cpu_spikes_vs_N")

        for n in common:
            save(
                over_time([
                    (on_label, enabled[n][0], on_color),
                    (off_label, disabled[n][0], off_color),
                ], n),
                pdf, destination, f"N{n}_over_time",
            )

    print(f"Compared N = {common}")
    print(f"Reports saved in {OUTPUT}")


if __name__ == "__main__":
    main()