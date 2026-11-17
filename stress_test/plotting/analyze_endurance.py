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