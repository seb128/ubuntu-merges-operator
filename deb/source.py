#!/usr/bin/env python
# -*- coding: utf-8 -*-
# deb/source.py - parse debian source control (dsc) files
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

from deb.controlfile import ControlFile
from deb.version import Version


# Regular expressions make validating things easy
valid_source = re.compile(r"^[a-z0-9][a-z0-9+.-]*$")
valid_filename = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+:.,_=-]*$")


class SourceControl(ControlFile):
    """Debian source control (dsc) file.

    Properties:
      dsc_format  Format of the dsc file
      source      Name of the source package
      version     Version information (as a Version object)
      files       List of accompanying files (as SourceFile objects)
      tar         Accompanying tar file
      diff        Accompanying diff file (if any)
    """

    def __init__(self, filename=None, fileobj=None):
        super(SourceControl, self).__init__()

        self.dsc_format = 1.0
        self.source = None
        self.version = None
        self.files = []
        self.tar = None
        self.diff = None

        if fileobj is not None:
            self.parse(fileobj)
        elif filename is not None:
            self.open(filename)

    def parse(self, file):
        """Parse source control (dsc) file.

        Parses the opened source control (dsc) file given, validates it
        and stores the most important information in the object.  The
        rest of the fields can still be accessed through the para
        member.
        """
        super(SourceControl, self).parse(file, signed=True)

        if "Format" in self.para:
            try:
                self.dsc_format = float(self.para["Format"])
                if int(self.dsc_format) != 1:
                    raise IOError
            except ValueError:
                raise IOError

        if "Source" in self.para:
            self.source = self.para["Source"]
            if not valid_source.search(self.source):
                raise IOError
        else:
            raise IOError

        if "Version" in self.para:
            self.version = Version(self.para["Version"])
        else:
            raise IOError

        if "Files" in self.para:
            files = self.para["Files"].strip("\n").split("\n")
            for f in files:
                try:
                    (md5sum, size, name) = f.split(None, 2)
                except ValueError:
                    raise IOError

                sf = SourceFile(name, size, md5sum)
                if name.endswith(".tar.gz"):
                    if self.tar:
                        raise IOError
                    self.tar = sf
                elif name.endswith(".diff.gz"):
                    if self.diff:
                        raise IOError
                    self.diff = sf
                self.files.append(sf)

            if not self.tar:
                raise IOError
        else:
            raise IOError


class SourceFile(object):
    """File belonging to a Debian source package.

    Properties:
      name        Relative filename of the file
      size        Expected size of the file
      md5sum      Expected md5sum of the file
    """

    def __init__(self, name, size, md5sum):
        if not valid_filename.search(name):
            raise ValueError

        self.name = name
        self.size = size
        self.md5sum = md5sum

    def __str__(self):
        """Return the name of the file."""
        return self.name
