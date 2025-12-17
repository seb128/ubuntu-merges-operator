#!/usr/bin/env python
# stats-graphs.py - output stats graphs
#
# Copyright © 2008 Canonical Ltd.
# Author: Scott James Remnant <scott@ubuntu.com>.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of version 3 of the GNU General Public License as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import calendar
import datetime
import logging

from momlib import DISTROS, OUR_DISTRO, ROOT, run

import matplotlib.pyplot as plt
import matplotlib.dates as mdates

logging.getLogger("matplotlib").setLevel(logging.WARNING)

# Order of stats we pick out
ORDER = [
    "needs-merge",
    "modified",
    "unmodified",
    "needs-sync",
    "local",
    "repackaged",
]

# Labels used on the graph
LABELS = {
    "unmodified": "Unmodified",
    "needs-sync": "Needs Sync",
    "local": "Local",
    "repackaged": "Repackaged",
    "modified": "Modified",
    "needs-merge": "Needs Merge",
}

# Colours (fill styles) used for each stat
FILL_STYLES = {
    "unmodified": "blue",
    "needs-sync": "darkorchid",
    "local": "aquamarine",
    "repackaged": "green",
    "modified": "yellow",
    "needs-merge": "red",
}

# Offsets of individual stats on the pie chart (for pulling out)
ARC_OFFSETS = {
    "unmodified": 10,
    "needs-sync": 10,
    "local": 0,
    "repackaged": 5,
    "needs-merge": 0,
    "modified": 0,
}


def options(parser):
    parser.add_option(
        "-d",
        "--distro",
        type="string",
        metavar="DISTRO",
        default=OUR_DISTRO,
        help="Distribution to generate stats for",
    )


def main(options, args):
    distro = options.distro

    # Read from the stats file
    stats = read_stats()

    # Get the range of the trend chart
    today = datetime.date.today()
    start = trend_start(today)
    events = get_events(stats, start)

    # Iterate the components and calculate the peaks over the last six
    # months, as well as the current stats
    for component in DISTROS[distro]["components"]:
        # Extract current and historical stats for this component
        current = get_current(stats[component])
        history = get_history(stats[component], start)

        pie_chart(component, current)
        range_chart(component, history, start, today, events)


def date_to_datetime(s):
    """Convert a date string into a datetime."""
    (year, mon, day) = (int(x) for x in s.split("-", 2))
    return datetime.date(year, mon, day)


def date_to_ordinal(s):
    """Convert a date string into an ordinal."""
    return date_to_datetime(s).toordinal()


def ordinal_to_label(o):
    """Convert an ordinal into a chart label."""
    d = datetime.date.fromordinal(int(o))
    return d.strftime("/hL{}%b %y")


def trend_start(today):
    """Return the date from which to begin displaying the trend chart."""
    if today.month > 9:
        s_year = today.year
        s_month = today.month - 9
    else:
        s_year = today.year - 1
        s_month = today.month + 3

    s_day = min(calendar.monthrange(s_year, s_month)[1], today.day)
    start = datetime.date(s_year, s_month, s_day)

    return start


def read_stats():
    """Read the stats history file."""
    stats = {}

    stats_file = "%s/stats.txt" % ROOT
    with open(stats_file) as stf:
        for line in stf:
            (date, time, component, info) = line.strip().split(" ", 3)

            if component not in stats:
                stats[component] = []

            stats[component].append([date, time, info])

    return stats


def get_events(stats, start):
    """Get the list of interesting events."""
    events = []

    if "event" in stats:
        for date, time, info in stats["event"]:
            if date_to_datetime(date) >= start:
                events.append((date, info))

    return events


def info_to_data(date, info):
    """Convert an optional date and information set into a data set."""
    data = []
    if date is not None:
        data.append(date)

    values = dict(p.split("=", 1) for p in info.split(" "))
    for key in ORDER:
        data.append(int(values[key]))

    return data


def get_current(stats):
    """Get the latest information."""
    (date, time, info) = stats[-1]
    return info


def get_history(stats, start):
    """Get historical information for each day since start."""
    values = {}
    for date, time, info in stats:
        if date_to_datetime(date) >= start:
            values[date] = info

    dates = sorted(values)

    return [(d, values[d]) for d in dates]


def date_tics(min, max):
    """Return list of tics between the two ordinals."""
    intervals = []
    for tic in range(min, max + 1):
        if datetime.date.fromordinal(tic).day == 1:
            intervals.append(tic)

    return intervals


def sources_intervals(max):
    """Return the standard and minimal interval for the sources axis."""
    if max > 10000:
        return (10000, 2500)
    elif max > 1000:
        return (1000, 250)
    elif max > 100:
        return (100, 25)
    elif max > 10:
        return (10, 2.5)
    else:
        return (1, None)


def pie_chart(component, current):
    """Output a pie chart for the given component and data."""
    values = info_to_data(None, current)
    labels = [LABELS[key] for key in ORDER]

    explode = [ARC_OFFSETS[key] / 100.0 for key in ORDER]
    colors = [FILL_STYLES[key] for key in ORDER]

    fig, ax = plt.subplots(figsize=(7, 7))

    ax.pie(
        values,
        explode=explode,
        labels=labels,
        colors=colors,
        shadow=True,
        startangle=90,
        autopct="%1.1f%%",
        wedgeprops={"edgecolor": "black", "linewidth": 0.5},
    )

    ax.axis("equal")

    filename = f"{ROOT}/merges/{component}-now.png"
    plt.savefig(filename, bbox_inches="tight")
    plt.close(fig)


def range_chart(component, history, start, today, events):
    """Output a range chart for the given component and data."""

    data_list = [info_to_data(date, info) for date, info in history]

    if not data_list:
        return

    dates_ordinal = [date_to_datetime(d[0]) for d in data_list]
    raw_values = [[d[i] for d in data_list] for i in range(1, 7)]

    colors = [FILL_STYLES[key] for key in ORDER]
    labels = [LABELS[key] for key in ORDER]

    # figsize in inches (900x450 pixels)
    fig, ax = plt.subplots(figsize=(12, 6))

    ax.stackplot(
        dates_ordinal,
        *raw_values,
        labels=labels,
        colors=colors,
        edgecolor="black",
        linewidth=0.2,
    )

    ax.set_xlim(start, today)

    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonthday=1))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))

    plt.xticks(rotation=45, ha="right", fontsize=9)
    ax.set_xlabel("Date", fontsize=10)

    max_y = max(sum(y) for y in zip(*raw_values)) if raw_values else 10
    y_major, y_minor = sources_intervals(max_y)

    ax.yaxis.set_major_locator(plt.MultipleLocator(y_major))
    if y_minor:
        ax.yaxis.set_minor_locator(plt.MultipleLocator(y_minor))

    ax.set_ylabel("Sources", fontsize=10)
    ax.set_ylim(0, max_y * 1.1)  # 10% top margin

    ax.legend(loc="upper left", fontsize=9, frameon=True)
    ax.grid(True, axis="y", linestyle=":", alpha=0.6)

    levels = {}
    y_limit = ax.get_ylim()[1]

    for date_str, text in events:
        d_ord = date_to_ordinal(date_str)

        ax.axvline(
            x=d_ord, color="black", linestyle="--", linewidth=0.7, alpha=0.5
        )
        x_pix, _ = ax.transData.transform((d_ord, 0))

        level = 0
        while level < 3:
            if levels.get(level, -1) < x_pix:
                break
            level += 1

        offset_y = 20 + (level * 25)

        ax.annotate(
            text,
            xy=(d_ord, y_limit),
            xytext=(10, offset_y),
            textcoords="offset points",
            fontsize=8,
            arrowprops={"arrowstyle": "->", "color": "black", "lw": 0.5},
            bbox={
                "boxstyle": "round,pad=0.2",
                "fc": "white",
                "ec": "gray",
                "alpha": 0.8,
            },
        )

        levels[level] = x_pix + (len(text) * 6) + 20

    filename = f"{ROOT}/merges/{component}-trend.png"
    plt.savefig(filename, bbox_inches="tight", dpi=100)
    plt.close(fig)


if __name__ == "__main__":
    run(main, options, usage="%prog", description="output stats graphs")
