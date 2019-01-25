#!/usr/bin/env python
# -*- coding: utf-8 -*-
# check-pool.py - check the pool against Launchpad
#
# Copyright © 2016 Canonical Ltd.
# Author: Colin Watson <cjwatson@ubuntu.com>.
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

from __future__ import print_function

import hashlib
import logging
import os.path
import shutil
import tempfile

from momlib import (
    DISTROS,
    download_source,
    get_pool_distros,
    get_pool_sources,
    get_sources,
    run,
)


def options(parser):
    parser.add_option(
        "-d",
        "--distro",
        type="string",
        metavar="DISTRO",
        action="append",
        help="Process only these distros",
    )
    parser.add_option(
        "-p",
        "--package",
        type="string",
        metavar="PACKAGE",
        action="append",
        help="Process only these packages",
    )


class Mismatch(Exception):
    pass


def check_source(distro, source):
    tdir = tempfile.mkdtemp()
    try:
        download_source(distro, source, tdir)
        for fieldname, hashname, hasher in (
            ("Checksums-Sha512", "SHA-512", hashlib.sha512),
            ("Checksums-Sha256", "SHA-256", hashlib.sha256),
            ("Checksums-Sha1", "SHA-1", hashlib.sha1),
            ("Files", "MD5", hashlib.md5),
        ):
            if fieldname not in source:
                continue
            for entry in source[fieldname].strip("\n").split("\n"):
                expected_hash, expected_size, name = entry.split(None, 2)
                with open(os.path.join(tdir, name), "rb") as f:
                    h = hasher()
                    for chunk in iter(lambda: f.read(256 * 1024), ""):
                        h.update(chunk)
                    if h.hexdigest() != expected_hash:
                        raise Mismatch(
                            "%s %s: LP %s != pool %s"
                            % (name, hashname, h.hexdigest(), expected_hash)
                        )
    finally:
        shutil.rmtree(tdir)


def main(options, args):
    for distro in get_pool_distros():
        if options.distro is not None and distro not in options.distro:
            continue
        sourcenames = set()
        for dist in DISTROS[distro]["dists"]:
            for component in DISTROS[distro]["components"]:
                for source in get_sources(distro, dist, component):
                    sourcenames.add(source["Package"])
        for sourcename in sorted(sourcenames):
            if (
                options.package is not None
                and sourcename not in options.package
            ):
                continue
            try:
                sources = get_pool_sources(distro, sourcename)
            except IOError:
                continue
            for source_entry in sources:
                try:
                    check_source(distro, source_entry)
                except IOError:
                    # Already logged above.
                    pass
                except Mismatch as e:
                    logging.warning("%s %s: %s" % (distro, sourcename, e))


if __name__ == "__main__":
    run(
        main,
        options,
        usage="%prog",
        description="check the pool against Launchpad",
    )
