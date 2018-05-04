#!/usr/bin/env python
# -*- coding: utf-8 -*-
# expire-pool.py - expires packages from all pools
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

from collections import defaultdict
import glob
import logging
import os.path

from momlib import (
    DISTROS,
    files,
    get_base,
    get_pool_distros,
    get_pool_sources,
    get_sources,
    OUR_DIST,
    OUR_DISTRO,
    pool_directory,
    ROOT,
    run,
    update_pool_sources,
    version_sort,
    )
from util import tree


def options(parser):
    parser.add_option("-p", "--package", type="string", metavar="PACKAGE",
                      action="append",
                      help="Process only these packages")


def main(options, args):
    if len(args):
        distros = args
    else:
        distros = get_pool_distros()

    # Run through our default distribution and use that for the base
    # package names.  Expire from all distributions.
    our_sources = set()
    for component in DISTROS[OUR_DISTRO]["components"]:
        for source in get_sources(OUR_DISTRO, OUR_DIST, component):
            our_sources.add(source["Package"])
            if (options.package is not None and
                    source["Package"] not in options.package):
                continue

            base = get_base(source)
            logging.debug("%s %s", source["Package"], source["Version"])
            logging.debug("base is %s", base)

            for distro in distros:
                if DISTROS[distro]["expire"]:
                    expire_pool_sources(distro, source["Package"], base)

    for distro in distros:
        if not DISTROS[distro]["expire"]:
            continue

        distro_sources = defaultdict(list)
        for dist in DISTROS[distro]["dists"]:
            for component in DISTROS[distro]["components"]:
                for source in get_sources(distro, dist, component):
                    distro_sources[source["Package"]].append(source)

        # Packages not in our default distribution won't have been expired
        # above.  For these, we don't need to do particularly sophisticated
        # expiry, but just remove any files that aren't in the
        # distribution's Sources file.
        if distro != OUR_DISTRO:
            for package in sorted(distro_sources):
                if package in our_sources:
                    continue
                if (options.package is not None and
                        package not in options.package):
                    continue

                distro_versions = set(
                    source["Version"] for source in distro_sources[package])

                try:
                    pool_sources = get_pool_sources(distro, package)
                except IOError:
                    pass
                else:
                    remove_sources = [
                        source for source in pool_sources
                        if source["Version"] not in distro_versions]
                    version_sort(remove_sources)
                    expire_sources(
                        distro, package,
                        distro_sources[package], remove_sources)

        # Any pool directories whose sources are in neither the default
        # distribution nor their own distribution are entirely obsolete, so
        # remove them.
        for pooldir in glob.iglob("%s/pool/%s/*/*" % (ROOT, distro)):
            name = os.path.basename(pooldir)
            if options.package is not None and name not in options.package:
                continue
            if (name not in our_sources and name not in distro_sources and
                    os.path.isdir(pooldir)):
                tree.remove(pooldir)
                logging.debug("Removed %s", pooldir)


def expire_pool_sources(distro, package, base):
    """Remove sources older than the given base.

    If the base doesn't exist, then the newest source that is older is also
    kept.
    """
    try:
        sources = get_pool_sources(distro, package)
    except IOError:
        return

    # Find sources older than the base, record the filenames of newer ones
    bases = []
    base_found = False
    keep = []
    for source in sources:
        if base > source["Version"]:
            bases.append(source)
        else:
            if base == source["Version"]:
                base_found = True
                logging.info("Leaving %s %s %s (is base)", distro, package,
                             source["Version"])
            else:
                logging.info("Leaving %s %s %s (is newer)", distro, package,
                             source["Version"])

            keep.append(source)

    # If the base wasn't found, we want the newest source below that
    if not base_found and len(bases):
        version_sort(bases)
        source = bases.pop()
        logging.info("Leaving %s %s %s (is newest before base)",
                     distro, package, source["Version"])

        keep.append(source)

    expire_sources(distro, package, keep, bases)


def expire_sources(distro, package, keep_sources, remove_sources):
    pooldir = pool_directory(distro, package)

    # Identify filenames we don't want to delete
    keep_files = set()
    for source in keep_sources:
        for _, name in files(source):
            keep_files.add(name)

    # Expire the older packages
    need_update = False
    for source in remove_sources:
        logging.info("Expiring %s %s %s", distro, package, source["Version"])

        for _, name in files(source):
            if name in keep_files:
                logging.debug("Not removing %s/%s", pooldir, name)
                continue

            tree.remove("%s/%s/%s" % (ROOT, pooldir, name))
            logging.debug("Removed %s/%s", pooldir, name)
            need_update = True

    if need_update:
        update_pool_sources(distro, package)


if __name__ == "__main__":
    run(main, options, usage="%prog [DISTRO...]",
        description="expires packages from all pools")
