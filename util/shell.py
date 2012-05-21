#!/usr/bin/env python
# -*- coding: utf-8 -*-
# util/shell.py - child process forking (popen-alike)
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
import sys
import signal


class Process(object):
    """Child process.

    This class implements execution and management of child processes
    including providing input and capturing their output.

    If a process is opened in either 'read' or 'write' mode, the object
    wraps an internal file object, you can call read(), write() or
    indeed access any other member through this object.

    | p = Process(('ls', '/'), 'r')
    | p.read()
    or
    | for print in p:
    |     print filename
    | p.close()
    """

    def __init__(self, args, mode="x", stdin=None, stdout=None, stderr=None,
                 chdir=None, okstatus=(0,), env=None):
        """Spawn a child process.

        The command name and its arguments should be provided as a tuple or
        list for the first argument, as no shell is involved there is no
        need to escape or quote special characters.

        The mode can be 'x' for plain execution (the default), 'r' for
        reading or 'w' for writing, additional mode characters are passed
        to the internal open so see Python's documentation for them.

        When a file is opened for reading or writing the object may be
        used as a file object and data read from or written to it.

        Standard input, output and error of the process can be redirected
        to other files you have open by passing them in the stdin, stdout
        and stderr arguments.  If the process is opened for writing you
        cannot redirect stdin, and if the process is opened for reading
        you cannot redirect stdout.

        All of the unused descriptors are redirected to /dev/null by
        default, you can override this by passing the real file descriptor
        again (eg. stdout=sys.stdout, stderr=sys.stderr).  Standard error
        can be redirected to standard output with stderr=sys.stdout,
        stdout can still redirected elsewhere without affecting this
        (eg. stdout=tmpfile, stderr=sys.stdout).  To redirect them both
        to the same place, pass the same file
        (eg. stdout=tmpfile, stderr=tmpfile)

        The process is normally run in the current working directory,
        that can be changed by passing the alternate directory in the chdir
        argument.

        You must call close() on the process to ensure it is reaped and
        to gain the exit status, even for those in execution mode (this
        allows you to run the process in the background for a while).
        Non-zero exit statuses are normally treated as a failure and an
        exception raised, if this is undesired specify the allowed exit
        status as a list or tuple in the okstatus argument.

        To set environment variables in the child, pass a dictionary in the
        env argument.  This should normally be a copy of os.environ with
        additional changes.  If not passed or None, the child inherits the
        parent's environment.
        """
        self.args = list(args)
        self.okstatus = okstatus

        # Sanity check mode
        self.mode = mode
        if not len(self.mode) or self.mode[0] not in "rwx":
            raise ValueError, "invalid mode: %s" % mode
        elif self.mode[0] == "r" and stdout is not None:
            raise ValueError, "cannot capture stdout when mode=r"
        elif self.mode[0] == "w" and stdin is not None:
            raise ValueError, "cannot provide stdin when mode=w"

        # Sanity check chdir
        if chdir is not None and not os.path.isdir(chdir):
            raise OSError, "cannot chdir to %s" % chdir

        if env is None:
            self.env = None
        else:
            self.env = dict(env)

        self.open(stdin, stdout, stderr, chdir)

    def open(self, stdin, stdout, stderr, chdir):
        """Spawn the process to do the work.

        This is called automatically by __init__ and is separated out to
        allow sub-classes to override __init__ or open as they see fit.
        """
        if self.mode[0] != "x":
            (pipe_r, pipe_w) = os.pipe()
        else:
            (pipe_r, pipe_w) = (None, None)

        self.pid = os.fork()
        if self.pid == 0:
            try:
                self.child(pipe_r, pipe_w, stdin, stdout, stderr, chdir)
            except OSError:
                os._exit(250)
            except Exception:
                os._exit(251)
            os._exit(252)

        elif self.pid > 0:
            # Parent
            if self.mode[0] == "r":
                os.close(pipe_w)
                self._pipe = os.fdopen(pipe_r, self.mode)
            elif self.mode[0] == "w":
                os.close(pipe_r)
                self._pipe = os.fdopen(pipe_w, self.mode)
            elif self.mode[0] == "x":
                self._pipe = None
        else:
            # Failure
            raise OSError, "%s failed" % " ".join(self.args)

    def child(self, pipe_r, pipe_w, stdin, stdout, stderr, chdir):
        """Child process.

        Called by open inside the child process, separated out so it can
        be easily wrapped to catch exceptions and make sure the process
        doesn't run away.
        """
        # Set up stderr first, so stderr=sys.stdout works
        if stderr is not None:
            if stderr == sys.stdout:
                os.dup2(sys.__stdout__.fileno(), sys.__stderr__.fileno())
            elif stderr != sys.stderr:
                os.dup2(stderr.fileno(), sys.__stderr__.fileno())
        else:
            with open("/dev/null", "w") as null:
                os.dup2(null.fileno(), sys.__stderr__.fileno())

        # Set up stdout
        if self.mode[0] == "r":
            os.close(pipe_r)
            os.dup2(pipe_w, sys.__stdout__.fileno())
        elif stdout is not None:
            if stdout == sys.stderr:
                os.dup2(sys.__stderr__.fileno(), sys.__stdout__.fileno())
            elif stdout != sys.stdout:
                os.dup2(stdout.fileno(), sys.__stdout__.fileno())
        else:
            with open("/dev/null", "w") as null:
                os.dup2(null.fileno(), sys.__stdout__.fileno())

        # Set up stdin
        if self.mode[0] == "w":
            os.close(pipe_w)
            os.dup2(pipe_r, sys.__stdin__.fileno())
        elif stdin is not None:
            if stdin != sys.stdin:
                os.dup2(stdin.fileno(), sys.__stdin__.fileno())
        else:
            with open("/dev/null", "r") as null:
                os.dup2(null.fileno(), sys.__stdin__.fileno())

        if chdir is not None:
            os.chdir(chdir)

        # Python's default disposition of SIG_IGN for SIGPIPE is not safe
        # for non-Python subprocesses.
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)

        # Run the command
        if self.env is None:
            os.execvp(self.args[0], self.args)
        else:
            os.execvpe(self.args[0], self.args, self.env)

    def close(self):
        """Close the process and file descriptor.

        Waits for the process to exit and cleans up afterwards.  You need
        to call this function to get the error status of the sub-process
        and ensure that it doesn't become a zombie.

        Returns the exit code of the process, to get non-zero you must
        have included the value you wanted in okstatus to init.
        """
        if self._pipe is not None:
            try:
                self._pipe.close()
            except IOError:
                # ignore broken pipe
                pass

        (pid, status) = os.waitpid(self.pid, 0)
        if not os.WIFEXITED(status):
            raise OSError, "abnormal exit: %s" % " ".join(self.args)
        elif os.WEXITSTATUS(status) == 250:
            raise OSError, "exec error: %s" % " ".join(self.args)
        elif os.WEXITSTATUS(status) == 251:
            raise OSError, "exec error: %s" % " ".join(self.args)
        elif os.WEXITSTATUS(status) == 252:
            raise OSError, "exec error: %s" % " ".join(self.args)
        elif os.WEXITSTATUS(status) not in self.okstatus:
            raise ValueError, "process failed %d: %s" \
                  % (os.WEXITSTATUS(status), " ".join(self.args))

        return os.WEXITSTATUS(status)

    def __iter__(self):
        """Wraps the iterator of the pipe."""
        if self._pipe is not None:
            return iter(self._pipe)
        else:
            raise AssertionError, "not open in read or write mode"

    def __getattr__(self, name):
        """Wraps all functions and properties of the pipe."""
        if self._pipe is not None:
            return getattr(self._pipe, name)
        else:
            raise AttributeError, "'%s' object has no attribute '%s'" \
                  % (type(self).__name__, name)


def run(args, stdin=None, stdout=None, stderr=None, chdir=None, okstatus=(0,),
        env=None):
    """Run a process without an input or output pipe.

    Shorthand for util.shell.Process(...) with mode fixed to 'x' and calls
    close immediately.
    """
    p = Process(args, "x", stdin=stdin, stdout=stdout, stderr=stderr,
                chdir=chdir, okstatus=okstatus, env=env)
    return p.close()

def get(args, stdin=None, stderr=None, chdir=None, okstatus=(0,), env=None,
        strip=True):
    """Get process output.

    Shorthand for util.shell.Process(...) with mode fixed to 'r' and
    all output read and returned as a string.

    If strip is True (the default) any final newlines will be stripped.
    """
    p = Process(args, "r", stdin=stdin, stderr=stderr, chdir=chdir,
                okstatus=okstatus, env=env)
    try:
        text = p.read()
        if strip:
            return text.rstrip("\r\n")
        else:
            return text
    finally:
        p.close()
