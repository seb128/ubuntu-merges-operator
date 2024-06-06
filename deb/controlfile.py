#!/usr/bin/env python
# -*- coding: utf-8 -*-
# deb/controlfile.py - parse debian control files
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

from typing import List


class ControlFile(object):
    """Debian control file.

    This can be used directly by calling the parse() function or
    overridden to add functionality.

    Class Properties:
      FieldNames  Alternate canonical capitalisation of field names

    Properties:
      paras       List of paragraphs as dictionaries
      para        Final (or single) paragraph
      signed      True if the paragraph was PGP signed
    """

    FieldNames: List[str] = []

    def __init__(self, filename=None, fileobj=None, *args, **kwds):
        self.paras = []
        self.para = None
        self.signed = False

        if fileobj is not None:
            self.parse(fileobj, *args, **kwds)
        elif filename is not None:
            self.open(filename, *args, **kwds)

    def capitaliseField(self, field):
        """Capitalise a field name correctly.

        Fields are stored in the dictionary canonically capitalised,
        words split by dashes and the first letter of each in upper
        case.

        This can be overriden by adding the canonical capitalisation
        of a field name to the FieldNames list.
        """
        for canon in self.FieldNames:
            if canon.lower() == field.lower():
                return canon

        return "-".join([w.title() for w in field.split("-")])

    def open(self, file, *args, **kwds):
        """Open and parse a control-file format file."""
        with open(file) as f:
            try:
                self.parse(f, *args, **kwds)
            except Exception as e:
                e.path = file
                raise e

    def parse(self, file, multi_para=False, signed=False):
        """Parse a control-file format file.

        File is any object that acts as an iterator and returns lines,
        file-like objects being most common.

        Some control files may contain multiple paragraphs separated
        by blank lines, if this is the case set multi_para to True.

        Some single-paragraph control files may be PGP signed, if this
        is the case set signed to True.  If the file was actually
        signed, the signed member of the object will be set to True.
        """
        self.para = {}
        is_signed = False
        last_field = None
        para_border = True

        for line in file:
            line = line.rstrip()
            if line.startswith("#"):
                continue

            # Multiple blank lines are permitted at paragraph borders
            if not len(line) and para_border:
                continue
            para_border = False

            if line[:1].isspace():
                if last_field is None:
                    raise IOError

                self.para[last_field] += "\n" + line.lstrip()

            elif ":" in line:
                (field, value) = line.split(":", 1)
                if len(field.rstrip().split(None)) > 1:
                    raise IOError

                last_field = self.capitaliseField(field)
                self.para[last_field] = value.lstrip()

            elif line.startswith("-----BEGIN PGP") and signed:
                if is_signed:
                    raise IOError
                for line in file:
                    if not len(line) or line.startswith("\n"):
                        break
                is_signed = True

            elif not len(line):
                para_border = True
                if multi_para:
                    self.paras.append(self.para)
                    self.para = {}
                    last_field = None

                elif is_signed:
                    try:
                        pgpsig = next(file)
                        if not len(pgpsig):
                            raise IOError
                    except StopIteration:
                        raise IOError

                    if not pgpsig.startswith("-----BEGIN PGP"):
                        raise IOError

                    self.signed = True
                    break

                else:
                    raise IOError

            else:
                raise IOError

        if is_signed and not self.signed:
            raise IOError

        if last_field:
            self.paras.append(self.para)
        elif len(self.paras):
            self.para = self.paras[-1]
