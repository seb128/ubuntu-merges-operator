#!/usr/bin/python3
# generate-diffs.py - generate changes and diff files for new packages
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
import subprocess

from momlib import (
    DISTROS,
    ROOT,
    changes_file,
    cleanup_source,
    diff_file,
    get_pool_distros,
    get_pool_sources,
    get_sources,
    read_blocklist,
    run,
    save_basis,
    save_changes_file,
    save_patch_file,
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

    blocklist = read_blocklist()

    # For each package in the given distributions, iterate the pool in order
    # and generate a diff from the previous version and a changes file
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
                    if source["Package"] in blocklist:
                        continue

                    try:
                        sources = get_pool_sources(distro, source["Package"])
                    except OSError:
                        continue  # already expired
                    version_sort(sources)

                    last = None
                    try:
                        for this in sources:
                            try:
                                generate_diff(distro, last, this)
                            finally:
                                if last is not None:
                                    cleanup_source(last)

                            last = this
                    finally:
                        if last is not None:
                            cleanup_source(last)


def generate_diff(distro, last, this):
    """Generate the differences."""
    logging.debug("%s: %s %s", distro, this["Package"], this["Version"])

    changes_filename = changes_file(distro, this)
    if not os.path.isfile(changes_filename) and not os.path.isfile(
        changes_filename + ".bz2",
    ):
        unpack_source(distro, this)
        try:
            save_changes_file(changes_filename, this, last)
            logging.info(
                "Saved changes file: %s",
                tree.subdir(ROOT, changes_filename),
            )
        except subprocess.CalledProcessError:
            logging.exception(
                "dpkg-genchanges for %s failed",
                tree.subdir(ROOT, changes_filename),
            )

    if last is None:
        return

    diff_filename = diff_file(distro, this)
    if not os.path.isfile(diff_filename) and not os.path.isfile(
        diff_filename + ".bz2",
    ):
        unpack_source(distro, this)
        unpack_source(distro, last)
        save_patch_file(diff_filename, last, this)
        save_basis(diff_filename, last["Version"])
        logging.info("Saved diff file: %s", tree.subdir(ROOT, diff_filename))


if __name__ == "__main__":
    run(
        main,
        options,
        usage="%prog [DISTRO...]",
        description="generate changes and diff files for new packages",
    )
