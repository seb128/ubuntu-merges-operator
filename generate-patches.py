#!/usr/bin/env python
# -*- coding: utf-8 -*-
# generate-patches.py - generate patches between distributions
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
from re import search

from deb.version import Version
from momlib import (
    cleanup_source,
    DISTROS,
    ensure,
    get_base,
    get_nearest_source,
    get_pool_source,
    get_same_source,
    get_sources,
    OUR_DIST,
    OUR_DISTRO,
    patch_file,
    read_basis,
    read_blacklist,
    ROOT,
    run,
    save_basis,
    save_patch_file,
    SRC_DIST,
    SRC_DISTRO,
    unpack_source,
)
from util import tree


def options(parser):
    parser.add_option(
        "-f", "--force", action="store_true", help="Force creation of patches"
    )

    parser.add_option(
        "-D",
        "--source-distro",
        type="string",
        metavar="DISTRO",
        default=SRC_DISTRO,
        help="Source distribution",
    )
    parser.add_option(
        "-S",
        "--source-suite",
        type="string",
        metavar="SUITE",
        default=SRC_DIST,
        help="Source suite (aka distrorelease)",
    )

    parser.add_option(
        "-d",
        "--dest-distro",
        type="string",
        metavar="DISTRO",
        default=OUR_DISTRO,
        help="Destination distribution",
    )
    parser.add_option(
        "-s",
        "--dest-suite",
        type="string",
        metavar="SUITE",
        default=OUR_DIST,
        help="Destination suite (aka distrorelease)",
    )

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
        help="Process only these destination components",
    )


def main(options, args):
    src_distro = options.source_distro
    src_dist = options.source_suite

    our_distro = options.dest_distro
    our_dist = options.dest_suite

    blacklist = read_blacklist()

    # For each package in the destination distribution, locate the latest in
    # the source distribution; calculate the base from the destination and
    # create patches from that to both
    for our_component in DISTROS[our_distro]["components"]:
        if (
            options.component is not None
            and our_component not in options.component
        ):
            continue

        for our_source in get_sources(our_distro, our_dist, our_component):
            if (
                options.package is not None
                and our_source["Package"] not in options.package
            ):
                continue
            if our_source["Package"] in blacklist:
                continue

            if search(".*build[0-9]+$", our_source["Version"]):
                continue

            try:
                package = our_source["Package"]
                our_version = Version(our_source["Version"])
                our_pool_source = get_pool_source(
                    our_distro, package, our_version
                )
                logging.debug("%s: %s is %s", package, our_distro, our_version)
            except (IOError, IndexError):
                continue

            try:
                (src_source, src_version, src_pool_source) = get_same_source(
                    src_distro, src_dist, package
                )
                logging.debug("%s: %s is %s", package, src_distro, src_version)
            except IndexError:
                continue

            try:
                base = get_base(our_source)
                make_patches(
                    our_distro,
                    our_pool_source,
                    src_distro,
                    src_pool_source,
                    base,
                    force=options.force,
                )

                slip_base = get_base(our_source, slip=True)
                if slip_base != base:
                    make_patches(
                        our_distro,
                        our_pool_source,
                        src_distro,
                        src_pool_source,
                        slip_base,
                        True,
                        force=options.force,
                    )
            finally:
                cleanup_source(our_pool_source)
                cleanup_source(src_pool_source)


def make_patches(
    our_distro,
    our_source,
    src_distro,
    src_source,
    base,
    slipped=False,
    force=False,
):
    """Make sets of patches from the given base."""
    package = our_source["Package"]
    try:
        base_source = get_nearest_source(package, base)
        base_version = Version(base_source["Version"])
        logging.debug(
            "%s: base is %s (%s wanted)", package, base_version, base
        )
    except IndexError:
        return

    try:
        generate_patch(
            src_distro, base_source, our_distro, our_source, slipped, force
        )
        generate_patch(
            src_distro, base_source, src_distro, src_source, slipped, force
        )
    finally:
        cleanup_source(base_source)


def generate_patch(
    base_distro, base_source, distro, our_source, slipped=False, force=False
):
    """Generate a patch file for the given comparison."""
    our_version = Version(our_source["Version"])
    base_version = Version(base_source["Version"])

    if base_version > our_version:
        # Allow comparison of source -1 against our -0ubuntuX (slipped)
        if not slipped:
            return
        elif our_version.revision is None:
            return
        elif not our_version.revision.startswith("0ubuntu"):
            return
        elif base_version.revision != "1":
            return
        elif base_version.upstream != our_version.upstream:
            return
        elif base_version.epoch != our_version.epoch:
            return

        logging.debug("Allowing comparison of -1 against -0ubuntuX")
    elif base_version == our_version:
        return

    filename = patch_file(distro, our_source, slipped)
    if not force:
        basis = read_basis(filename)
        if basis is not None and basis == base_version:
            return

    unpack_source(base_distro, base_source)
    unpack_source(distro, our_source)

    ensure(filename)
    save_patch_file(filename, base_source, our_source)
    save_basis(filename, base_version)
    logging.info("Saved patch file: %s", tree.subdir(ROOT, filename))


if __name__ == "__main__":
    run(
        main,
        options,
        usage="%prog",
        description="generate patches between distributions",
    )
