#!/usr/bin/env python
# deb/version.py - parse and compare Debian version strings.
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

import re

# Regular expressions make validating things easy
valid_epoch = re.compile(r"^[0-9]+$")
valid_upstream = re.compile(r"^[A-Za-z0-9+:.~-]*$")
valid_revision = re.compile(r"^[A-Za-z0-9+.~]+$")

# Character comparison table for upstream and revision components
cmp_table = "~ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz+-.:"


class Version:
    """Debian version number.

    This class is designed to be reasonably transparent and allow you
    to write code like:

    |   s.version >= '1.100-1'

    The comparison will be done according to Debian rules, so '1.2' will
    compare lower.

    Properties:
      epoch       Epoch
      upstream    Upstream version
      revision    Debian/local revision
    """

    def __init__(self, ver):
        """Parse a string or number into the three components."""
        self.epoch = 0
        self.revision = None

        ver = str(ver)
        if not len(ver):
            raise ValueError

        # Epoch is component before first colon
        idx = ver.find(":")
        epoch_str = "0"
        if idx != -1:
            epoch_str = ver[:idx]
            if not len(epoch_str):
                raise ValueError
            if not valid_epoch.search(epoch_str):
                raise ValueError
            ver = ver[idx + 1 :]

        # Revision is component after last hyphen
        idx = ver.rfind("-")
        if idx != -1:
            self.revision = ver[idx + 1 :]
            if not len(self.revision):
                raise ValueError
            if not valid_revision.search(self.revision):
                raise ValueError
            ver = ver[:idx]

        # Remaining component is upstream
        self.upstream = ver
        if not len(self.upstream):
            raise ValueError
        if not valid_upstream.search(self.upstream):
            raise ValueError

        self.epoch = int(epoch_str)

    def getWithoutEpoch(self):
        """Return the version without the epoch."""
        str = self.upstream
        if self.revision is not None:
            str += "-%s" % (self.revision,)
        return str

    without_epoch = property(getWithoutEpoch)

    def __str__(self):
        """Return the class as a string for printing."""
        str = ""
        if self.epoch > 0:
            str += "%d:" % (self.epoch,)
        str += self.upstream
        if self.revision is not None:
            str += "-%s" % (self.revision,)
        return str

    def __repr__(self):
        """Return a debugging representation of the object."""
        return "<%s epoch: %d, upstream: %r, revision: %r>" % (
            self.__class__.__name__,
            self.epoch,
            self.upstream,
            self.revision,
        )

    def __lt__(self, other):
        return self.__cmp__(other) == -1

    def __gt__(self, other):
        return self.__cmp__(other) == 1

    def __eq__(self, other):
        return self.__cmp__(other) == 0

    def __le__(self, other):
        return self.__cmp__(other) <= 0

    def __ge__(self, other):
        return self.__cmp__(other) >= 0

    def __cmp__(self, other):
        """Compare two Version classes."""
        other = Version(other)
        if self.epoch < other.epoch:
            return -1
        if self.epoch > other.epoch:
            return 1

        result = deb_cmp(self.upstream, other.upstream)
        if result != 0:
            return result

        result = deb_cmp(self.revision or "", other.revision or "")
        if result != 0:
            return result

        return 0


def strcut(str, idx, accept):
    """Cut characters from str that are entirely in accept."""
    ret = ""
    while idx < len(str) and str[idx] in accept:
        ret += str[idx]
        idx += 1

    return (ret, idx)


def deb_order(str, idx):
    """Return the comparison order of two characters."""
    if idx >= len(str):
        return 0
    elif str[idx] == "~":
        return -1
    else:
        return cmp_table.index(str[idx])


def deb_cmp_str(x, y):
    """Compare two strings in a deb version."""
    idx = 0
    while (idx < len(x)) or (idx < len(y)):
        result = deb_order(x, idx) - deb_order(y, idx)
        if result < 0:
            return -1
        elif result > 0:
            return 1

        idx += 1

    return 0


def deb_cmp(x, y):
    """Implement the string comparison outlined by Debian policy."""
    x_idx = y_idx = 0
    while x_idx < len(x) or y_idx < len(y):
        # Compare strings
        (x_str, x_idx) = strcut(x, x_idx, cmp_table)
        (y_str, y_idx) = strcut(y, y_idx, cmp_table)
        result = deb_cmp_str(x_str, y_str)
        if result != 0:
            return result

        # Compare numbers
        (x_str, x_idx) = strcut(x, x_idx, "0123456789")
        (y_str, y_idx) = strcut(y, y_idx, "0123456789")
        if int(x_str or "0") < int(y_str or "0"):
            return -1
        if int(x_str or "0") > int(y_str or "0"):
            return 1

    return 0
