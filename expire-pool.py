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

import logging

from momlib import *
from util import tree


def main(options, args):
    if len(args):
        distros = args
    else:
        distros = get_pool_distros()

    # Run through our default distribution and use that for the base
    # package names.  Expire from all distributions.
    for component in DISTROS[OUR_DISTRO]["components"]:
        for source in get_sources(OUR_DISTRO, OUR_DIST, component):
            base = get_base(source)
            logging.debug("%s %s", source["Package"], source["Version"])
            logging.debug("base is %s", base)

            for distro in distros:
                if DISTROS[distro]["expire"]:
                    expire_pool_sources(distro, source["Package"], base)


def expire_pool_sources(distro, package, base):
    """Remove sources older than the given base.

    If the base doesn't exist, then the newest source that is older is also
    kept.
    """
    pooldir = pool_directory(distro, package)
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

    # Identify filenames we don't want to delete
    keep_files = []
    for source in keep:
        for _, name in files(source):
            keep_files.append(name)

    # Expire the older packages
    need_update = False
    for source in bases:
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
    run(main, usage="%prog [DISTRO...]",
        description="expires packages from all pools")
