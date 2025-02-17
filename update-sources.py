#!/usr/bin/env python
# update-sources.py - update the Sources files in a distribution's pool
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
import sys

from momlib import ROOT, get_pool_distros, run, update_pool_sources


def main(options, args):
    if len(args):
        distros = args
    else:
        distros = get_pool_distros()

    # Iterate the pool directory of the given distributions
    for distro in distros:
        try:
            hparts = os.listdir("%s/pool/%s" % (ROOT, distro))
        except OSError as e:
            print(e, "(continuing)", file=sys.stderr)
            continue
        for hpart in hparts:
            print(f"Updating pool for {distro}/{hpart}")
            for package in os.listdir("%s/pool/%s/%s" % (ROOT, distro, hpart)):
                update_pool_sources(distro, package)


if __name__ == "__main__":
    run(
        main,
        usage="%prog [DISTRO...]",
        description="update the Sources file in a distribution's pool",
    )
