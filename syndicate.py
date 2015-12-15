#!/usr/bin/env python
# -*- coding: utf-8 -*-
# syndicate.py - send out e-mails and update rss feeds
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

import os
import bz2
import fcntl
import logging

from email.MIMEMultipart import MIMEMultipart
from email.MIMEText import MIMEText
from email.Utils import formatdate, make_msgid, parseaddr
from fnmatch import fnmatch
from smtplib import SMTP, SMTPSenderRefused, SMTPDataError

from momlib import *
from deb.controlfile import ControlFile
from deb.version import Version


def options(parser):
    parser.add_option("-p", "--package", type="string", metavar="PACKAGE",
                      action="append",
                      help="Process only theses packages")
    parser.add_option("-c", "--component", type="string", metavar="COMPONENT",
                      action="append",
                      help="Process only these components")

def main(options, args):
    if len(args):
        distros = args
    else:
        distros = get_pool_distros()

    subscriptions = read_subscriptions()

    patch_rss = read_rss(patch_rss_file(),
                         title="Ubuntu Patches from Debian",
                         link="http://patches.ubuntu.com/",
                         description="This feed announces new patches from "
                         "Ubuntu to Debian, each patch filename contains "
                         "the complete difference between the two "
                         "distributions for that package.")

    diff_rss = read_rss(diff_rss_file(),
                        title="Ubuntu Uploads",
                        link="http://patches.ubuntu.com/by-release/atomic/",
                        description="This feed announces new changes in "
                        "Ubuntu, each patch filename contains the difference "
                        "between the new version and the previous one.")


    # For each package in the given distributions, iterate the pool in order
    # and select various interesting files for syndication
    for distro in distros:
        for dist in DISTROS[distro]["dists"]:
            for component in DISTROS[distro]["components"]:
                if options.component is not None \
                       and component not in options.component:
                    continue

                for source in get_sources(distro, dist, component):
                    if options.package is not None \
                           and source["Package"] not in options.package:
                        continue

                    watermark = read_watermark(distro, source)
                    sources = get_pool_sources(distro, source["Package"])
                    version_sort(sources)

                    for this in sources:
                        if watermark < this["Version"]:
                            break
                    else:
                        continue

                    this_patch_rss = read_rss(patch_rss_file(distro, source),
                                             title="Ubuntu Patches from Debian for %s" % source["Package"],
                                             link=("http://patches.ubuntu.com/by-release/" +
                                                   tree.subdir("%s/patches" % ROOT,
                                                               patch_directory(distro, source))),
                                              description="This feed announces new patches from "
                                              "Ubuntu to Debian for %s, each patch filename contains "
                                              "the complete difference between the two "
                                              "distributions for that package." % source["Package"])
                    this_diff_rss = read_rss(diff_rss_file(distro, source),
                                             title="Ubuntu Uploads for %s" % source["Package"],
                                             link=("http://patches.ubuntu.com/by-release/atomic/" +
                                                   tree.subdir("%s/diffs" % ROOT,
                                                               diff_directory(distro, source))),
                                             description="This feed announces new changes in "
                                             "Ubuntu for %s, each patch filename contains the "
                                             "difference between the new version and the "
                                             "previous one." % source["Package"])

                    last = None
                    for this in sources:
                        if watermark >= this["Version"]:
                            last = this
                            continue

                        logging.debug("%s: %s %s", distro,
                                      this["Package"], this["Version"])

                        changes_filename = changes_file(distro, this)
                        if os.path.isfile(changes_filename):
                            changes = open(changes_filename)
                        elif os.path.isfile(changes_filename + ".bz2"):
                            changes = bz2.BZ2File(changes_filename + ".bz2")
                        else:
                            logging.warning(
                                "Missing changes file %s" % changes_filename)
                            continue

                        # Extract the author's e-mail from the changes file
                        try:
                            info = ControlFile(fileobj=changes,
                                               multi_para=False,
                                               signed=False).para
                            if "Changed-By" not in info:
                                uploader = None
                            else:
                                uploader = parseaddr(info["Changed-By"])[-1]
                        finally:
                            changes.close()

                        update_feeds(distro, last, this, uploader,
                                     patch_rss, this_patch_rss,
                                     diff_rss, this_diff_rss)

                        try:
                            mail_diff(distro, last, this, uploader,
                                      subscriptions)
                        except MemoryError:
                            logging.error("Ran out of memory")

                        last = this

                    write_rss(patch_rss_file(distro, source), this_patch_rss)
                    write_rss(diff_rss_file(distro, source), this_diff_rss)
                    save_watermark(distro, source, this["Version"])

    write_rss(patch_rss_file(), patch_rss)
    write_rss(diff_rss_file(), diff_rss)


def mail_diff(distro, last, this, uploader, subscriptions):
    """Mail a diff out to the subscribers."""
    recipients = get_recipients(distro, this["Package"],
                                uploader, subscriptions)
    if not len(recipients):
        return

    if distro == SRC_DISTRO:
        # Debian uploads always just have a diff
        subject = "Debian %s %s" % (this["Package"], this["Version"])
        intro = MIMEText("""\
This e-mail has been sent due to an upload to Debian, and contains the
difference between the new version and the previous one.""")
        payload = diff_part(distro, this)
    elif distro != OUR_DISTRO:
        # Other uploads always just have a diff
        subject = "%s %s %s" % (distro, this["Package"], this["Version"])
        intro = MIMEText("""\
This e-mail has been sent due to an upload to %s, and contains the
difference between the new version and the previous one.""" % distro)
        payload = diff_part(distro, this)
    elif get_base(this) == this["Version"]:
        # Never e-mail ubuntu uploads without local changes
        return
    elif last is None:
        # Initial ubuntu uploads, send the patch
        subject = "Ubuntu (new) %s %s" % (this["Package"], this["Version"])
        intro = MIMEText("""\
This e-mail has been sent due to an upload to Ubuntu of a new source package
which already contains Ubuntu changes.  It contains the difference between
the Ubuntu version and the equivalent base version in Debian.""")
        payload = patch_part(distro, this)
    elif get_base(last) != get_base(this):
        # Ubuntu changed upstream version, send the patech
        subject = "Ubuntu (new upstream) %s %s"\
                  % (this["Package"], this["Version"])
        intro = MIMEText("""\
This e-mail has been sent due to an upload to Ubuntu of a new upstream
version which still contains Ubuntu changes.  It contains the difference
between the Ubuntu version and the equivalent base version in Debian, note
that this difference may include the upstream changes.""")
        payload = patch_part(distro, this)
    else:
        # Ubuntu revision, send the diff
        subject = "Ubuntu %s %s" % (this["Package"], this["Version"])
        intro = MIMEText("""\
This e-mail has been sent due to an upload to Ubuntu that contains Ubuntu
changes.  It contains the difference between the new version and the
previous version of the same source package in Ubuntu.""")
        payload = diff_part(distro, this)

    # Allow patches to be missing (no Debian version)
    if payload is None:
        return

    # Extract the changes file
    changes_filename = changes_file(distro, this)
    if os.path.isfile(changes_filename):
        changes = MIMEText(open(changes_filename).read())
    elif os.path.isfile(changes_filename + ".bz2"):
        changes = MIMEText(bz2.BZ2File(changes_filename + ".bz2").read())
    changes.add_header("Content-Disposition", "inline",
                       filename="%s" % os.path.basename(changes_filename))

    # Build up the message
    message = MIMEMultipart()
    message.add_header("From", "Ubuntu Merge-o-Matic <mom@ubuntu.com>")
    message.add_header("To", "Ubuntu Merge-o-Matic <mom@ubuntu.com>")
    message.add_header("Date", formatdate())
    message.add_header("Subject", subject)
    message.add_header("Message-ID", make_msgid())
    message.add_header("X-Your-Mom", "mom.ubuntu.com %s" % this["Package"])
    message.add_header("X-PTS-Approved", "yes")
    message.add_header("X-Distro-Tracker-Package", this["Package"])
    message.add_header("X-Distro-Tracker-Keyword", "derivatives")
    message.attach(intro)
    message.attach(changes)
    message.attach(payload)

    send_message(message, recipients)

def patch_part(distro, this):
    """Construct an e-mail part containing the current patch."""
    patch_filename = patch_file(distro, this, True)
    if os.path.isfile(patch_filename):
        part = MIMEText(open(patch_filename).read())
    elif os.path.isfile(patch_filename + ".bz2"):
        part = MIMEText(bz2.BZ2File(patch_filename + ".bz2").read())
    else:
        patch_filename = patch_file(distro, this, False)
        if os.path.isfile(patch_filename):
            part = MIMEText(open(patch_filename).read())
        elif os.path.isfile(patch_filename + ".bz2"):
            part = MIMEText(bz2.BZ2File(patch_filename + ".bz2").read())
        else:
            return None

    part.add_header("Content-Disposition", "attachment",
                    filename="%s" % os.path.basename(patch_filename))
    return part

def diff_part(distro, this):
    """Construct an e-mail part containing the current diff."""
    diff_filename = diff_file(distro, this)
    if os.path.isfile(diff_filename):
        part = MIMEText(open(diff_filename).read())
    elif os.path.isfile(diff_filename + ".bz2"):
        part = MIMEText(bz2.BZ2File(diff_filename + ".bz2").read())
    else:
        return None

    part.add_header("Content-Disposition", "attachment",
                    filename="%s" % os.path.basename(diff_filename))
    return part


def get_recipients(distro, package, uploader, subscriptions):
    """Figure out who should receive this message."""
    recipients = []

    for sub_addr, sub_distro, sub_filter in subscriptions:
        sub_addr = sub_addr.replace("%s", package)

        if sub_distro != distro:
            continue

        if sub_filter.startswith("my:"):
            sub_filter = sub_filter[3:]

            if uploader != sub_addr:
                continue

        if not fnmatch(package, sub_filter):
            continue

        recipients.append(sub_addr)

    return recipients

def send_message(message, recipients):
    """Send out a message to everyone subscribed to it."""
    smtp = SMTP("localhost")

    for addr in recipients:
        if "##" in addr:
            (env_addr, addr) = addr.split("##")
        else:
            env_addr = addr

        logging.debug("Sending to %s", addr)
        message.replace_header("To", addr)

        try:
            smtp.sendmail("mom@ubuntu.com", env_addr , message.as_string())
        except (SMTPSenderRefused, SMTPDataError):
            logging.exception("smtp failed")
            smtp = SMTP("localhost")

    smtp.quit()


def update_feeds(distro, last, this, uploader, patch_rss, this_patch_rss,
                 diff_rss, this_diff_rss):
    """Update the various RSS feeds."""
    patch_filename = patch_file(distro, this, True)
    if os.path.isfile(patch_filename):
        pass
    elif os.path.isfile(patch_filename + ".bz2"):
        patch_filename += ".bz2"
    else:
        patch_filename = patch_file(distro, this, False)
        if os.path.isfile(patch_filename):
            pass
        elif os.path.isfile(patch_filename + ".bz2"):
            patch_filename += ".bz2"
        else:
            patch_filename = None

    if patch_filename is not None:
        append_rss(patch_rss,
                   title=os.path.basename(patch_filename),
                   link=("http://patches.ubuntu.com/by-release/" +
                         tree.subdir("%s/patches" % ROOT, patch_filename)),
                   author=uploader,
                   filename=patch_filename)

        append_rss(this_patch_rss,
                   title=os.path.basename(patch_filename),
                   link=("http://patches.ubuntu.com/by-release/" +
                         tree.subdir("%s/patches" % ROOT, patch_filename)),
                   author=uploader,
                   filename=patch_filename)

    diff_filename = diff_file(distro, this)
    if os.path.isfile(diff_filename):
        pass
    elif os.path.isfile(diff_filename + ".bz2"):
        diff_filename += ".bz2"
    else:
        diff_filename = None

    if diff_filename is not None:
        append_rss(diff_rss,
                   title=os.path.basename(diff_filename),
                   link=("http://patches.ubuntu.com/by-release/atomic/" +
                         tree.subdir("%s/diffs" % ROOT, diff_filename)),
                   author=uploader,
                   filename=diff_filename)

        append_rss(this_diff_rss,
                   title=os.path.basename(diff_filename),
                   link=("http://patches.ubuntu.com/by-release/atomic/" +
                         tree.subdir("%s/diffs" % ROOT, diff_filename)),
                   author=uploader,
                   filename=diff_filename)


def read_subscriptions():
    """Read the subscriptions file."""
    subscriptions = []

    with open("%s/subscriptions.txt" % ROOT) as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_SH)

        for line in f:
            if line.startswith("#"):
                continue

            (addr, distro, filter) = line.strip().split()
            subscriptions.append((addr, distro, filter))

    return subscriptions

def read_watermark(distro, source):
    """Read the watermark for a given source."""
    mark_file = "%s/%s/watermark" \
                % (ROOT, pool_directory(distro, source["Package"]))
    if not os.path.isfile(mark_file):
        return Version("0")

    with open(mark_file) as mark:
        return Version(mark.read().strip())

def save_watermark(distro, source, version):
    """Save the watermark for a given source."""
    mark_file = "%s/%s/watermark" \
                % (ROOT, pool_directory(distro, source["Package"]))
    with open(mark_file, "w") as mark:
        print("%s" % version, file=mark)


if __name__ == "__main__":
    run(main, options, usage="%prog [DISTRO...]",
        description="send out e-mails and update rss feeds")
