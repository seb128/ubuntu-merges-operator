#!/usr/bin/env python
# -*- coding: utf-8 -*-
# mail-bugs.py - mail list of closed bugs
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

from __future__ import print_function, with_statement

import bz2
from email.MIMEText import MIMEText
from email.Utils import formatdate, make_msgid
import logging
import os
import re
from smtplib import SMTP
import urllib2

from BeautifulSoup import BeautifulSoup

from deb.controlfile import ControlFile
from deb.version import Version
from momlib import (
    changes_file,
    DISTROS,
    get_pool_sources,
    get_sources,
    pool_directory,
    ROOT,
    run,
    SRC_DIST,
    SRC_DISTRO,
    version_sort,
    )


# Order of severities
SEVERITY = [ "unknown", "critical", "grave", "serious", "important", "normal",
             "minor", "wishlist" ]

# Who to send to
RECIPIENTS = [ "ubuntu-archive@lists.ubuntu.com",
               "ubuntu-devel@lists.ubuntu.com" ]


def options(parser):
    parser.add_option("-d", "--distro", type="string", metavar="DISTRO",
                      default=SRC_DISTRO,
                      help="Distribution to mail bug closures for")
    parser.add_option("-s", "--suite", type="string", metavar="SUITE",
                      default=SRC_DIST,
                      help="Suite (aka distrorelease)")

def main(options, args):
    distro = options.distro
    dist = options.suite

    bugs = []

    # For each package in the distribution, iterate the pool and read each
    # changes file to obtain the list of closed bugs.
    for component in DISTROS[distro]["components"]:
        for source in get_sources(distro, dist, component):
            package = source["Package"]

            watermark = read_watermark(distro, package)
            sources = get_pool_sources(distro, package)
            version_sort(sources)

            for this in sources:
                if watermark >= this["Version"]:
                    continue

                bugs.extend(closed_bugs(distro, this))

            save_watermark(distro, package, this["Version"])

    if len(bugs):
        mail_closures(bugs)

def closed_bugs(distro, this):
    """Obtain a list of closed bugs."""
    logging.debug("%s: %s %s", distro, this["Package"], this["Version"])

    changes_filename = changes_file(distro, this)
    if os.path.isfile(changes_filename):
        changes = open(changes_filename)
    elif os.path.isfile(changes_filename + ".bz2"):
        changes = bz2.BZ2File(changes_filename + ".bz2")
    else:
        logging.warning("Missing changes file %s" % changes_filename)
        return []

    # Extract the closes line from the changes file
    try:
        info = ControlFile(fileobj=changes,
                           multi_para=False, signed=False).para
    finally:
        changes.close()

    if "Closes" not in info:
        return []

    # DoS the Debian BTS to find the information
    bugs = []
    closes = [ c.strip() for c in info["Closes"].split() if len(c.strip()) ]
    for bug in closes:
        bug = int(bug)
        bugs.append(bug_info(this["Package"], bug))

    return bugs

def bug_info(package, bug):
    """Extract bug information from the Debian BTS."""
    logging.debug("Closes: %d", bug)
    url = "http://bugs.debian.org/cgi-bin/bugreport.cgi?bug=%d" % bug
    request = urllib2.Request(url, None)
    response = urllib2.urlopen(request)
    soup = BeautifulSoup(response.read())

    try:
        title = soup("h1")[0].contents[-1]
        title = title.replace("&quot;", "\"")
        title = title.replace("&lt;", "<")
        title = title.replace("&gt;", ">")
        title = title.replace("&amp;", "&")
        logging.debug("Title: %s", title)
    except IndexError:
        title = "(unknown)"

    severity = "normal"
    try:
        detail = re.sub(r'<[^>]*>', '',
                        "".join(str(c) for c in soup("h3")[0].contents))
        for line in detail.split("\n"):
            if line.endswith(";"):
                line = line[:-1]

            if line.startswith("Severity:"):
                severity = line[9:].strip()
    except IndexError:
        severity = "unknown"

    logging.debug("Severity: %s", severity)
    if severity in SEVERITY:
        severity = SEVERITY.index(severity)
    else:
        severity = 0

    return (severity, package, bug, title)


def mail_closures(bugs):
    """Send the list of closed bugs."""
    text = ""
    max_package = 0
    max_bug = 0

    bugs.sort()
    for bug_severity, package, bug, title in bugs:
        if len(package) > max_package:
            max_package = len(package)
        if len(str(bug)) > max_bug:
            max_bug = len(str(bug))

    for idx, severity in enumerate(SEVERITY):
        closures = [ bug for bug in bugs if bug[0] == idx ]
        if not len(closures):
            continue

        text += "%s\n" % severity
        text += ("-" * len(severity)) + "\n\n"

        for bug_severity, package, bug, title in closures:
            text += "%-*s  %-*d  %s\n" \
                    % (max_package, package, max_bug, bug, title)

        text += "\n"

    message = MIMEText(text)
    message.add_header("From", "Ubuntu Merge-o-Matic <mom@ubuntu.com>")
    message.add_header("To", "Ubuntu Merge-o-Matic <mom@ubuntu.com>")
    message.add_header("Date", formatdate())
    message.add_header("Subject", "Bugs closed in Debian")
    message.add_header("Message-ID", make_msgid())

    send_message(message, RECIPIENTS)

def send_message(message, recipients):
    """Send out a message to everyone subscribed to it."""
    smtp = SMTP("localhost")

    for addr in recipients:
        logging.debug("Sending to %s", addr)
        message.replace_header("To", addr)

        smtp.sendmail("mom@ubuntu.com", addr , message.as_string())

    smtp.quit()


def read_watermark(distro, package):
    """Read the watermark for a given package."""
    mark_file = "%s/%s/bugs-watermark" \
                % (ROOT, pool_directory(distro, package))
    if not os.path.isfile(mark_file):
        return Version("0")

    with open(mark_file) as mark:
        return Version(mark.read().strip())

def save_watermark(distro, package, version):
    """Save the watermark for a given packagesource."""
    mark_file = "%s/%s/bugs-watermark" \
                % (ROOT, pool_directory(distro, package))
    with open(mark_file, "w") as mark:
        print("%s" % version, file=mark)


if __name__ == "__main__":
    run(main, options, usage="%prog [DISTRO...]",
        description="mail list of closed bugs")
