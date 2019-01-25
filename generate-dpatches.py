#!/usr/bin/env python
# -*- coding: utf-8 -*-
# generate-dpatches.py - generate extracted debian patches for new packages
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

import logging
import os

from momlib import (
    cleanup_source,
    DISTROS,
    dpatch_directory,
    ensure,
    get_pool_distros,
    get_pool_sources,
    get_sources,
    read_blacklist,
    ROOT,
    run,
    unpack_directory,
    unpack_source,
    version_sort,
)
from util import tree


def options(parser):
    parser.add_option(
        "-p",
        "--package",
        type="string",
        metavar="PACKAGE",
        action="append",
        help="Process only these packages",
    )
    parser.add_option(
        "-c",
        "--component",
        type="string",
        metavar="COMPONENT",
        action="append",
        help="Process only these components",
    )


def main(options, args):
    if len(args):
        distros = args
    else:
        distros = get_pool_distros()

    blacklist = read_blacklist()

    # For each package in the given distributions, iterate the pool in order
    # and extract patches from debian/patches
    for distro in distros:
        for dist in DISTROS[distro]["dists"]:
            for component in DISTROS[distro]["components"]:
                if (
                    options.component is not None
                    and component not in options.component
                ):
                    continue

                for source in get_sources(distro, dist, component):
                    if (
                        options.package is not None
                        and source["Package"] not in options.package
                    ):
                        continue
                    if source["Package"] in blacklist:
                        continue

                    sources = get_pool_sources(distro, source["Package"])
                    version_sort(sources)

                    for source in sources:
                        generate_dpatch(distro, source)


def generate_dpatch(distro, source):
    """Generate the extracted patches."""
    logging.debug("%s: %s %s", distro, source["Package"], source["Version"])

    stamp = "%s/%s/dpatch-stamp-%s" % (
        ROOT,
        source["Directory"],
        source["Version"],
    )

    if not os.path.isfile(stamp):
        open(stamp, "w").close()

        unpack_source(distro, source)
        try:
            dirname = dpatch_directory(distro, source)
            extract_dpatches(dirname, source)
            logging.info("Saved dpatches: %s", tree.subdir(ROOT, dirname))
        finally:
            cleanup_source(source)


def extract_dpatches(dirname, source):
    """Extract patches from debian/patches."""
    srcdir = unpack_directory(source)
    patchdir = "%s/debian/patches" % srcdir

    if not os.path.isdir(patchdir):
        logging.debug("No debian/patches")
        return

    for patch in tree.walk(patchdir):
        if os.path.basename(patch) in [
            "00list",
            "series",
            "README",
            ".svn",
            "CVS",
            ".bzr",
            ".git",
        ]:
            continue
        elif not len(patch):
            continue

        logging.debug("%s", patch)
        src_filename = "%s/%s" % (patchdir, patch)
        dest_filename = "%s/%s" % (dirname, patch)

        ensure(dest_filename)
        tree.copyfile(src_filename, dest_filename)


if __name__ == "__main__":
    run(
        main,
        options,
        usage="%prog [DISTRO...]",
        description="generate changes and diff files for new packages",
    )
