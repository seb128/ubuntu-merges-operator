#!/usr/bin/env python
# -*- coding: utf-8 -*-
# publish-patches.py - publish patches for the given distribution
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

import os
import logging

from momlib import *
from util import tree


def options(parser):
    parser.add_option("-d", "--distro", type="string", metavar="DISTRO",
                      default=OUR_DISTRO,
                      help="Distribution to publish")
    parser.add_option("-s", "--suite", type="string", metavar="SUITE",
                      default=OUR_DIST,
                      help="Suite (aka distrorelease) to publish")

def main(options, args):
    distro = options.distro
    dist = options.suite

    blacklist = read_blacklist()

    # Write to a new list
    list_filename = patch_list_file()
    list_file = open(list_filename + ".new", "w")
    try:
        # For each package in the distribution, check for a patch for the
        # current version; publish if it exists, clean up if not
        for component in DISTROS[distro]["components"]:
            for source in get_sources(distro, dist, component):
                package = source["Package"]

                if package in blacklist:
                    continue

                # Publish slipped patches in preference to true-base ones
                slip_filename = patch_file(distro, source, True)
                filename = patch_file(distro, source, False)

                if os.path.isfile(slip_filename):
                    publish_patch(distro, source, slip_filename, list_file)
                elif os.path.isfile(filename):
                    publish_patch(distro, source, filename, list_file)
                else:
                    unpublish_patch(distro, source)
    finally:
        list_file.close()

    # Move the new list over the old one
    os.rename(list_filename + ".new", list_filename)


def publish_patch(distro, source, filename, list_file):
    """Publish the latest version of the patch for all to see."""
    publish_filename = published_file(distro, source)

    ensure(publish_filename)
    if os.path.isfile(publish_filename):
        os.unlink(publish_filename)
    os.link(filename, publish_filename)

    logging.info("Published %s", tree.subdir(ROOT, publish_filename))
    print >>list_file, "%s %s" % (source["Package"],
                                  tree.subdir("%s/published" % ROOT,
                                              publish_filename))

    # Remove older patches
    for junk in os.listdir(os.path.dirname(publish_filename)):
        junkpath = "%s/%s" % (os.path.dirname(publish_filename), junk)
        if os.path.isfile(junkpath) \
                and junk != os.path.basename(publish_filename):
            os.unlink(junkpath)

    # Publish extracted patches
    output = "%s/extracted" % os.path.dirname(publish_filename)
    if os.path.isdir(output):
        tree.remove(output)

    dpatch_dir = dpatch_directory(distro, source)
    if os.path.isdir(dpatch_dir):
        for dpatch in tree.walk(dpatch_dir):
            if not len(dpatch):
                continue

            src_filename = "%s/%s" % (dpatch_dir, dpatch)
            dest_filename = "%s/%s" % (output, dpatch)

            logging.info("Published %s", tree.subdir(ROOT, dest_filename))
            ensure(dest_filename)
            tree.copyfile(src_filename, dest_filename)

def unpublish_patch(distro, source):
    """Remove any published patch."""
    publish_dir = os.path.dirname(published_file(distro, source))
    cleanup(publish_dir)


if __name__ == "__main__":
    run(main, options, usage="%prog",
        description="publish patches for the given distribution")
