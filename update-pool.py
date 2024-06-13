#!/usr/bin/env python
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


import logging
import os
import subprocess
import sys
import tempfile
import multiprocessing
from contextlib import contextmanager
from urllib.request import urlretrieve

from momlib import (
    DISTROS,
    ROOT,
    changes_file,
    ensure,
    files,
    get_pool_distros,
    get_sources,
    pool_directory,
    read_blocklist,
    run,
    sources_file,
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
        "-j",
        "--jobs",
        type="int",
        metavar="JOBS",
        help="Number of download jobs to run in parallel",
        default=4,
    )


def main(options, args):
    if len(args):
        distros = args
    else:
        distros = get_pool_distros()

    blocklist = read_blocklist()
    jobs = int(options.jobs)

    # Download the current sources for the given distributions and download
    # any new contents into our pool
    for distro in distros:
        for dist in DISTROS[distro]["dists"]:
            for component in DISTROS[distro]["components"]:
                update_sources(distro, dist, component)

                sources = []
                for source in get_sources(distro, dist, component):
                    if (
                        options.package is not None
                        and source["Package"] not in options.package
                    ):
                        continue
                    if source["Package"] in blocklist:
                        continue
                    changes_filename = changes_file(distro, source)
                    if os.path.isfile(changes_filename) or os.path.isfile(
                        changes_filename + ".bz2",
                    ):
                        # It looks as though we've already processed and
                        # expired this.
                        continue
                    sources.append((distro, source))

                with multiprocessing.Pool(jobs) as pool:
                    pool.map(_update_pool_wrapper, sources)


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
            urlretrieve(url, compfilename)
        except OSError:
            logging.exception("Downloading %s failed", url)
            continue
        try:
            if url.endswith(".gz"):
                import gzip

                decompressor = gzip.GzipFile
            elif url.endswith(".xz"):
                if sys.version_info.major >= 3 and sys.version_info.minor >= 3:
                    import lzma

                    decompressor = lzma.LZMAFile
                else:

                    @contextmanager
                    def decompressor(name):
                        proc = subprocess.Popen(
                            ["xzcat", name], stdout=subprocess.PIPE,
                        )
                        yield proc.stdout
                        proc.stdout.close()
                        proc.wait()

            else:
                raise RuntimeError("Don't know how to decompress %s" % url)
            with decompressor(compfilename) as compfile:
                ensure(filename)
                with open(filename, "wb") as local:
                    local.write(compfile.read())
        finally:
            os.unlink(compfilename)

        logging.info("Saved %s", tree.subdir(ROOT, filename))
        return filename
    raise OSError(
        "No Sources found for %s/%s/%s" % (distro, dist, component),
    )


def _update_pool_wrapper(args):
    return update_pool(*args)


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
            urlretrieve(url, filename)
        except OSError as ex:
            logging.exception("Downloading %s failed", url)
            raise RuntimeError("Download failed") from ex
        logging.info("Saved %s", tree.subdir(ROOT, filename))


if __name__ == "__main__":
    run(
        main,
        options,
        usage="%prog [DISTRO...]",
        description="update a distribution's pool",
    )
