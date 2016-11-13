#!/usr/bin/env python
# -*- coding: utf-8 -*-
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

from __future__ import with_statement

import calendar
from contextlib import closing
import datetime

from pychart import (
    area,
    arrow,
    axis,
    canvas,
    chart_data,
    fill_style,
    font,
    legend,
    line_style,
    pie_plot,
    range_plot,
    text_box,
    theme,
    )

from momlib import (
    DISTROS,
    OUR_DISTRO,
    ROOT,
    run,
    )


# Order of stats we pick out
ORDER = [ "needs-merge", "modified", "unmodified",
          "needs-sync", "local", "repackaged" ]

# Labels used on the graph
LABELS = {
    "unmodified":  "Unmodified",
    "needs-sync":  "Needs Sync",
    "local":       "Local",
    "repackaged":  "Repackaged",
    "modified":    "Modified",
    "needs-merge": "Needs Merge",
    }

# Colours (fill styles) used for each stat
FILL_STYLES = {
    "unmodified":  fill_style.blue,
    "needs-sync":  fill_style.darkorchid,
    "local":       fill_style.aquamarine1,
    "repackaged":  fill_style.green,
    "modified":    fill_style.yellow,
    "needs-merge": fill_style.red,
    }

# Offsets of individual stats on the pie chart (for pulling out)
ARC_OFFSETS = {
    "unmodified":  10,
    "needs-sync":  10,
    "local":       0,
    "repackaged":  5,
    "needs-merge": 0,
    "modified":    0,
    }


def options(parser):
    parser.add_option("-d", "--distro", type="string", metavar="DISTRO",
                      default=OUR_DISTRO,
                      help="Distribution to generate stats for")

def main(options, args):
    distro = options.distro

    # Read from the stats file
    stats = read_stats()

    # Initialise pychart
    theme.use_color = True
    theme.reinitialize()

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
    (year, mon, day) = [ int(x) for x in s.split("-", 2) ]
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
    with open(stats_file, "r") as stf:
        for line in stf:
            (date, time, component, info) = line.strip().split(" ", 3)

            if component not in stats:
                stats[component] = []

            stats[component].append([date, time, info])

    return stats

def get_events(stats, start):
    """Get the list of interesting events."""
    events = []
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

    dates = sorted(values.keys())

    return [ (d, values[d]) for d in dates ]


def date_tics(min, max):
    """Return list of tics between the two ordinals."""
    intervals = []
    for tic in range(min, max+1):
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
    data = zip([ LABELS[key] for key in ORDER ],
               info_to_data(None, current))

    filename = "%s/merges/%s-now.png" % (ROOT, component)
    with closing(canvas.init(filename, format="png")) as c:
        ar = area.T(size=(300,250), legend=None,
                    x_grid_style=None, y_grid_style=None)

        plot = pie_plot.T(data=data, arrow_style=arrow.a0, label_offset=25,
                          shadow=(2, -2, fill_style.gray50),
                          arc_offsets=[ ARC_OFFSETS[key] for key in ORDER ],
                          fill_styles=[ FILL_STYLES[key] for key in ORDER ])
        ar.add_plot(plot)

        ar.draw(c)

def range_chart(component, history, start, today, events):
    """Output a range chart for the given component and data."""
    data = chart_data.transform(lambda x: [ date_to_ordinal(x[0]),
                                            sum(x[1:1]),
                                            sum(x[1:2]),
                                            sum(x[1:3]),
                                            sum(x[1:4]),
                                            sum(x[1:5]),
                                            sum(x[1:6]),
                                            sum(x[1:7]) ],
                                [ info_to_data(date, info)
                                        for date, info in history ])

    (y_tic_interval, y_minor_tic_interval) = \
                     sources_intervals(max(d[-1] for d in data))

    filename = "%s/merges/%s-trend.png" % (ROOT, component)
    with closing(canvas.init(filename, format="png")) as c:
        ar = area.T(size=(450,225), legend=legend.T(),
                    x_axis=axis.X(label="Date", format=ordinal_to_label,
                                  tic_interval=date_tics,
                                  tic_label_offset=(10,0)),
                    y_axis=axis.Y(label="Sources", format="%d",
                                  tic_interval=y_tic_interval,
                                  minor_tic_interval=y_minor_tic_interval,
                                  tic_label_offset=(-10,0),
                                  label_offset=(-10,0)),
                    x_range=(start.toordinal(), today.toordinal()))

        for idx, key in enumerate(ORDER):
            plot = range_plot.T(data=data, label=LABELS[key],
                                min_col=idx+1, max_col=idx+2,
                                fill_style=FILL_STYLES[key])
            ar.add_plot(plot)

        ar.draw(c)

        levels = [ 0, 0, 0 ]

        for date, text in events:
            xpos = ar.x_pos(date_to_ordinal(date))
            ypos = ar.loc[1] + ar.size[1]

            for level, bar in enumerate(levels):
                if bar < xpos:
                    width = int(font.text_width(text))
                    levels[level] = xpos + 25 + width
                    break
            else:
                continue

            tb = text_box.T(loc=(xpos + 25, ypos + 45 - (20 * level)),
                            text=text)
            tb.add_arrow((xpos, ypos))
            tb.draw()

            c.line(line_style.black_dash2, xpos, ar.loc[1], xpos, ypos)


if __name__ == "__main__":
    run(main, options, usage="%prog",
        description="output stats graphs")
