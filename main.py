"""GTA VI launch-day Twitch viewer forecaster (gta6-twitch-ccu-forecast-01).

For each case, forecasts hours 2..24 of the release day as five quantiles
(5%, 25%, 50%, 75%, 95%) of the Twitch category's concurrent viewers.

Method, in one paragraph: the house baseline assumes the day stays flat at
the hour-1 count, but real launch days follow a daily curve -- a dip in the
early hours, a climb as the big markets unlock, an evening peak, a late fall.
That curve is learned from the case's own comparables (past big launches).
Each comparable is reduced to its release-day shape: the log ratio of each
hour's viewers to its hour-1 viewers. Games whose hour-1 print is a sliver
of their day peak (under 5%) are dropped -- they had not really unlocked by
hour 1, so their ratios are meaningless. The key regularity is that the
shape depends on how big hour 1 already is: a launch already huge at hour 1
has little headroom left (its peak is barely above hour 1), while a small
hour 1 leaves a lot of room to grow (the correlation between log hour-1 and
log peak ratio across comparables is about -0.77). So the comparables are
split into thirds by hour-1 size and the forecast uses only the third the
target's hour-1 falls in. Within that third, each hour's five quantiles are
the empirical quantiles of the log ratios at the five scored levels; the
spread is widened 25% around the median (the raw tertile intervals cover a
little under 90% of hours) and the log-quantile curves are lightly smoothed
across neighbouring hours, since a real audience curve does not jump
hour to hour. The forecast for hour h is then hour-1 print times exp of
the log-ratio quantile. Everything is done in log space, so a very small or
very large hour-1 print stays sensible.

Standard library only. Deterministic: same input bytes give same output
bytes (no randomness, no wall clock, no dict-order dependence -- every
collection is sorted before use). Fast: a case is a few tens of thousands
of hourly points; the whole run is well under a second.
"""

import json
import math
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
# Standard-normal quantiles at the five levels (used only by the fallback).
Z = [-1.645, -0.674, 0.0, 0.674, 1.645]

# A comparable counts only if its hour-1 print is at least this fraction of
# its own release-day peak: below it, the game had not unlocked by hour 1
# and its hour ratios are not a shape at all (they run to hundreds of x).
MIN_HOUR1_FRACTION = 0.05
# Widen the tertile spread this much around the median, in log space.
SPREAD_INFLATION = 1.25
# Minimum comparables in a tertile before falling back to the whole set.
MIN_TERTILE_SIZE = 8
# Minimum ratios in a tertile for one hour before widening the pool to
# every usable comparable for that hour (see _forecast_case).
MIN_HOUR_RATIOS = 3


def _parse_time(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")


def _release_day_hours(comp):
    """Hourly viewers {1..24: viewers} on the comparable's release day (UTC)."""
    day_start = _parse_time(comp["day_start"])
    day_end = day_start + timedelta(days=1)
    hours = {}
    for point in comp.get("hourly", []):
        viewers = point.get("viewers")
        if viewers is None or viewers <= 0:
            continue
        when = _parse_time(point["from"])
        if day_start <= when < day_end:
            hour = int((when - day_start).total_seconds() // 3600) + 1
            if 1 <= hour <= 24:
                hours[hour] = viewers
    return hours


def _quantile(sorted_values, level):
    """Linear-interpolation quantile of an already sorted list."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = level * (len(sorted_values) - 1)
    low = int(pos)
    frac = pos - low
    if low + 1 >= len(sorted_values):
        return sorted_values[-1]
    return sorted_values[low] * (1.0 - frac) + sorted_values[low + 1] * frac


def _round2(value):
    """Round to 2 decimals, half up (matches the kit starter's rounding)."""
    scaled = value * 100.0
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    rounded = whole / 100.0
    return int(rounded) if rounded.is_integer() else rounded


def _hour1_print(case):
    for row in case.get("known", []):
        if row.get("hour") == 1:
            return max(1, row.get("viewers", 1))
    return 1


def _ratio_curves(case):
    """Log-ratio curves of the usable comparables: [(hour1, {hour: log ratio})]."""
    curves = []
    for comp in sorted(case.get("comparables", []), key=lambda c: c.get("name", "")):
        hours = _release_day_hours(comp)
        if 1 not in hours or len(hours) < 20:
            continue
        peak = max(hours.values())
        if hours[1] / peak < MIN_HOUR1_FRACTION:
            continue
        curves.append(
            (hours[1], {h: math.log(v / hours[1]) for h, v in hours.items() if h >= 2})
        )
    return curves


def _tertile(curves, hour1):
    """The comparables in the same hour-1-size third as the target."""
    sizes = sorted(h1 for h1, _ in curves)
    cut_low = sizes[len(sizes) // 3]
    cut_high = sizes[2 * len(sizes) // 3]
    if hour1 < cut_low:
        group = [c for c in curves if c[0] < cut_low]
    elif hour1 < cut_high:
        group = [c for c in curves if cut_low <= c[0] < cut_high]
    else:
        group = [c for c in curves if c[0] >= cut_high]
    return group if len(group) >= MIN_TERTILE_SIZE else curves


def _forecast_case(case):
    hour1 = _hour1_print(case)
    curves = _ratio_curves(case)
    if not curves:
        # No usable history at all: fall back to the flat house baseline.
        return {
            "hours": [
                {
                    "hour": row["hour"],
                    "q": [
                        _round2(hour1 * math.exp(z * 0.15 * math.sqrt(row["hour"] - 1)))
                        for z in Z
                    ],
                }
                for row in case["forecast"]
            ]
        }
    group = _tertile(curves, hour1)
    # Per-hour log-ratio quantiles within the tertile, spread widened
    # around the median.
    log_q = {}
    for hour in range(2, 25):
        ratios = sorted(c[1][hour] for c in group if hour in c[1])
        if len(ratios) < MIN_HOUR_RATIOS:
            # Too few comparables in this tertile report this hour. With
            # none, the median below would silently fall back to a flat
            # forecast (quantile of [] is 0.0); with one, all five
            # quantiles would collapse to that single curve. Widen the
            # pool to every usable comparable for this hour, as the
            # tertile fallback already does for a too-small tertile.
            ratios = sorted(c[1][hour] for c in curves if hour in c[1])
        median = _quantile(ratios, 0.5)
        log_q[hour] = [
            median + SPREAD_INFLATION * (_quantile(ratios, level) - median)
            for level in LEVELS
        ]
    # Light smoothing across neighbouring hours (3-hour centred mean on
    # the log quantiles), then back to viewer counts.
    hours_out = []
    for row in case["forecast"]:
        hour = row["hour"]
        qs = []
        for level_i in range(len(LEVELS)):
            window = [
                log_q[h][level_i]
                for h in (hour - 1, hour, hour + 1)
                if 2 <= h <= 24
            ]
            qs.append(hour1 * math.exp(sum(window) / len(window)))
        # Clamp to the allowed range and round; re-enforce non-decreasing
        # after rounding.
        qs = [min(max(q, 1.0), 1e9) for q in qs]
        qs = [_round2(q) for q in qs]
        for i in range(1, len(qs)):
            if qs[i] < qs[i - 1]:
                qs[i] = qs[i - 1]
        hours_out.append({"hour": hour, "q": qs})
    hours_out.sort(key=lambda r: r["hour"])
    return {"hours": hours_out}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = _forecast_case(case)
        text = json.dumps(forecast, separators=(",", ":")) + "\n"
        (OUTPUT_DIR / (path.stem + ".out")).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
