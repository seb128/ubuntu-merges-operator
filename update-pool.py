#!/usr/bin/env python
# -*- coding: utf-8 -*-
# update-pool.py - update a distribution's pool
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
import urllib
import logging
import subprocess
import sys
import tempfile
from contextlib import contextmanager

from momlib import *
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

    # Download the current sources for the given distributions and download
    # any new contents into our pool
    for distro in distros:
        for dist in DISTROS[distro]["dists"]:
            for component in DISTROS[distro]["components"]:
                update_sources(distro, dist, component)

                sources = get_sources(distro, dist, component)
                for source in sources:
                    if options.package is not None \
                           and source["Package"] not in options.package:
                        continue
                    changes_filename = changes_file(distro, source)
                    if (os.path.isfile(changes_filename) or
                        os.path.isfile(changes_filename + ".bz2")):
                        # It looks as though we've already processed and
                        # expired this.
                        continue
                    update_pool(distro, source)


def sources_urls(distro, dist, component):
    """Return possible URLs for a remote Sources file."""
    mirror = DISTROS[distro]["mirror"]
    base_url = "%s/dists/%s/%s/source/Sources" % (mirror, dist, component)
    yield "%s.xz" % base_url
    yield "%s.gz" % base_url

def update_sources(distro, dist, component):
    """Update a Sources file."""
    for url in sources_urls(distro, dist, component):
        filename = sources_file(distro, dist, component)

        logging.debug("Downloading %s", url)

        compfilename = tempfile.mktemp()
        try:
            urllib.URLopener().retrieve(url, compfilename)
        except IOError:
            logging.error("Downloading %s failed", url)
            continue
        try:
            if url.endswith(".gz"):
                import gzip
                decompressor = gzip.GzipFile
            elif url.endswith(".xz"):
                if sys.version >= "3.3":
                    import lzma
                    decompressor = lzma.LZMAFile
                else:
                    @contextmanager
                    def decompressor(name):
                        proc = subprocess.Popen(
                            ["xzcat", name], stdout=subprocess.PIPE)
                        yield proc.stdout
                        proc.stdout.close()
                        proc.wait()
            else:
                raise RuntimeError("Don't know how to decompress %s" % url)
            with decompressor(compfilename) as compfile:
                ensure(filename)
                with open(filename, "w") as local:
                    local.write(compfile.read())
        finally:
            os.unlink(compfilename)

        logging.info("Saved %s", tree.subdir(ROOT, filename))
        return filename
    else:
        raise IOError(
            "No Sources found for %s/%s/%s" % (distro, dist, component))

def update_pool(distro, source):
    """Download a source package into our pool."""
    mirror = DISTROS[distro]["mirror"]
    sourcedir = source["Directory"]

    pooldir = pool_directory(distro, source["Package"])

    for size, name in files(source):
        url = "%s/%s/%s" % (mirror, sourcedir, name)
        filename = "%s/%s/%s" % (ROOT, pooldir, name)

        if os.path.isfile(filename):
            if os.path.getsize(filename) == int(size):
                continue

        logging.debug("Downloading %s", url)
        ensure(filename)
        try:
            urllib.URLopener().retrieve(url, filename)
        except IOError:
            logging.error("Downloading %s failed", url)
            raise
        logging.info("Saved %s", tree.subdir(ROOT, filename))


if __name__ == "__main__":
    run(main, options, usage="%prog [DISTRO...]",
        description="update a distribution's pool")
