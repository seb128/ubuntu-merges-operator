#!/usr/bin/env python
# -*- coding: utf-8 -*-
# stats.py - collect difference stats
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

import os
import time
import logging

from momlib import *
from deb.version import Version


def options(parser):
    parser.add_option("-D", "--source-distro", type="string", metavar="DISTRO",
                      default=SRC_DISTRO,
                      help="Source distribution")
    parser.add_option("-S", "--source-suite", type="string", metavar="SUITE",
                      default=SRC_DIST,
                      help="Source suite (aka distrorelease)")

    parser.add_option("-d", "--dest-distro", type="string", metavar="DISTRO",
                      default=OUR_DISTRO,
                      help="Destination distribution")
    parser.add_option("-s", "--dest-suite", type="string", metavar="SUITE",
                      default=OUR_DIST,
                      help="Destination suite (aka distrorelease)")

    parser.add_option("-p", "--package", type="string", metavar="PACKAGE",
                      action="append",
                      help="Process only theses packages")
    parser.add_option("-c", "--component", type="string", metavar="COMPONENT",
                      action="append",
                      help="Process only these destination components")

def main(options, args):
    src_distro = options.source_distro
    src_dist = options.source_suite

    our_distro = options.dest_distro
    our_dist = options.dest_suite

    blacklist = read_blacklist()

    # For each package in the destination distribution, locate the latest in
    # the source distribution; calculate the base from the destination
    for our_component in DISTROS[our_distro]["components"]:
        stats = {}
        stats["total"] = 0
        stats["local"] = 0
        stats["unmodified"] = 0
        stats["needs-sync"] = 0
        stats["needs-merge"] = 0
        stats["repackaged"] = 0
        stats["modified"] = 0

        if options.component is not None \
               and our_component not in options.component:
            continue

        for our_source in get_sources(our_distro, our_dist, our_component):
            if options.package is not None \
                   and our_source["Package"] not in options.package:
                continue

            package = our_source["Package"]
            our_version = Version(our_source["Version"])
            logging.debug("%s: %s is %s", package, our_distro, our_version)

            stats["total"] += 1

            if package in blacklist:
                logging.debug("%s: blacklisted (locally packaged)", package)
                stats["local"] += 1
                continue

            try:
                (src_source, src_version, src_pool_source) \
                             = get_same_source(src_distro, src_dist, package)
                logging.debug("%s: %s is %s", package, src_distro, src_version)
            except IndexError:
                logging.debug("%s: locally packaged", package)
                stats["local"] += 1
                continue

            base = get_base(our_source)

            if our_version == src_version:
                logging.debug("%s: unmodified", package)
                stats["unmodified"] += 1
            elif base > src_version:
                logging.debug("%s: locally repackaged", package)
                stats["repackaged"] += 1
            elif our_version == base:
                logging.debug("%s: needs sync", package)
                stats["needs-sync"] += 1
            elif our_version < src_version:
                logging.debug("%s: needs merge", package)
                stats["needs-merge"] += 1
            elif "-0ubuntu" in str(our_version):
                logging.debug("%s: locally repackaged", package)
                stats["repackaged"] += 1
            else:
                logging.debug("%s: modified", package)
                stats["modified"] += 1

        write_stats(our_component, stats)

def write_stats(component, stats):
    """Write out the collected stats."""
    stats_file = "%s/stats.txt" % ROOT
    with open(stats_file, "a") as stf:
        stamp = time.strftime("%Y-%m-%d %H:%M", time.gmtime())
        text = " ".join("%s=%d" % (k, v) for k,v in stats.items())
        print >>stf, "%s %s %s" % (stamp, component, text)

if __name__ == "__main__":
    run(main, options, usage="%prog",
        description="collect difference stats")
