#!/usr/bin/env python
# -*- coding: utf-8 -*-
# util/tree.py - useful functions for dealing with trees of files
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

import errno
import os
import shutil
import stat


def as_dir(path):
    """Return the path with a trailing slash."""
    if path.endswith("/"):
        return path
    elif len(path):
        return path + "/"
    else:
        return ""


def as_file(path):
    """Return the path without a trailing slash."""
    while path[-1:] == "/":
        path = path[:-1]
    return path


def relative(path):
    """Return the path without a leading slash."""
    while path[:1] == "/":
        path = path[1:]
    return path


def under(root, path):
    """Return whether a path is underneath a given root."""
    if as_dir(root) == as_dir(path):
        return True
    elif path.startswith(as_dir(root)):
        return True
    else:
        return False


def subdir(root, path):
    """Return path relative to root."""
    if not under(root, path):
        raise ValueError("path must start with root")

    return relative(path[len(root) :])


def walk(path, topdown=True, relative=True):
    """Returns an iterator to walk over a tree.

    Yields the relative path to each subdirectory name and filename
    within it.  This will also yield "" for the top-level directory name.

    If topdown is False the name of a directory will be yielded after
    its contents, rather than before.

    If relative is False the path is not stripped from the directory name.
    """
    for dirpath, dirnames, filenames in os.walk(path, topdown=topdown):
        if relative:
            base = subdir(path, dirpath)
        else:
            base = dirpath

        if topdown:
            yield base

        for filename in filenames:
            yield os.path.join(base, filename)

        # os.walk doesn't check for symlinks, so we do
        for dirname in list(dirnames):
            if os.path.islink(os.path.join(dirpath, dirname)):
                dirnames.remove(dirname)
                yield os.path.join(base, dirname)

        if not topdown:
            yield base


def copytree(path, newpath, link=False, dereference=False):
    """Create a copy of the tree at path under newpath.

    Copies a directory tree from one location to another, or if link is
    True the copy is hardlinked to the original.  Symbolic links are
    preserved unless dereference is True.  All other permissions are
    retained.
    """
    for filename in walk(path):
        copyfile(
            os.path.join(path, filename),
            os.path.join(newpath, filename),
            link=link,
            dereference=dereference,
        )


def copyfile(srcpath, dstpath, link=False, dereference=False):
    """Copy a file from one path to another.

    This is not recursive, if given a directory it simply makes the
    destination one.
    """
    dstpath = as_file(dstpath)
    if exists(dstpath):
        if os.path.isdir(dstpath) and not os.path.islink(dstpath):
            os.rmdir(dstpath)
        else:
            os.unlink(dstpath)

    parent = os.path.dirname(dstpath)
    if not exists(parent):
        os.makedirs(parent)

    if os.path.islink(srcpath) and not dereference:
        linkdest = os.readlink(srcpath)
        os.symlink(linkdest, dstpath)
    elif os.path.isdir(srcpath):
        os.makedirs(dstpath)
    elif stat.S_ISFIFO(os.stat(srcpath).st_mode):
        os.mkfifo(dstpath)
    elif link:
        os.link(srcpath, dstpath)
    else:
        shutil.copy2(srcpath, dstpath)


def movetree(path, newpath, eat_toplevel=False):
    """Move the contents of one tree into another.

    The newpath must either not exist in which case it is created, or
    be a directory.

    If eat_toplevel is True then if path contains only one item which is
    a directory, that is eaten and the contents of that moved into newpath.
    """
    if not os.path.isdir(newpath) or os.path.islink(newpath):
        if exists(newpath):
            raise OSError("Not a directory: %s" % newpath)
        else:
            os.makedirs(newpath)

    entries = os.listdir(path)
    if (
        eat_toplevel
        and len(entries) == 1
        and os.path.isdir(os.path.join(path, entries[0]))
        and not os.path.islink(os.path.join(path, entries[0]))
    ):
        movetree(os.path.join(path, entries[0]), newpath)
    else:
        for entry in entries:
            os.rename(os.path.join(path, entry), os.path.join(newpath, entry))

    os.rmdir(path)


def rmtree(path):
    """Remove the contents of a tree.

    A tree and all of its contents are removed if it exists.  It is safe
    to call this function if you don't know whether the destination exists
    or not.
    """
    if not exists(path):
        return

    for filename in walk(path, topdown=False, relative=False):
        try:
            if os.path.islink(filename):
                os.unlink(filename)
            elif os.path.isdir(filename):
                os.rmdir(filename)
            else:
                os.unlink(filename)
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise


def remove(filename):
    """Remove a symlink, file or directory tree."""
    try:
        if os.path.islink(filename):
            os.unlink(filename)
        elif os.path.isdir(filename):
            rmtree(filename)
        elif os.path.exists(filename):
            os.unlink(filename)
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise


def exists(path):
    """Return whether a path exists."""
    if os.path.exists(path):
        return True
    elif os.path.islink(path):
        return True
    else:
        return False


class AtomicFile(object):
    """Facilitate atomic writing of files."""

    def __init__(self, filename):
        self.filename = filename

    def __enter__(self):
        self.fd = open("%s.new" % self.filename, "w")
        return self.fd

    def __exit__(self, exc_type, unused_exc_value, unused_exc_tb):
        self.fd.close()
        if exc_type is None:
            os.rename("%s.new" % self.filename, self.filename)
