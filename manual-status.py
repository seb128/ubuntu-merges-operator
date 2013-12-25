#!/usr/bin/env python
# -*- coding: utf-8 -*-
# manual-status.py - output status of manual merges
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
import re
import time

from rfc822 import parseaddr
from momlib import *


# Order of priorities
PRIORITY = [ "unknown", "required", "important", "standard", "optional",
             "extra" ]
COLOURS =  [ "#ff8080", "#ffb580", "#ffea80", "#dfff80", "#abff80", "#80ff8b" ]

# Sections
SECTIONS = [ "new", "updated" ]


def options(parser):
    parser.add_option("-D", "--source-distro", type="string", metavar="DISTRO",
                      default=SRC_DISTRO,
                      help="Source distribution")
    parser.add_option("-S", "--source-suite", type="string", metavar="SUITE",
                      default=SRC_DIST,
                      help="Source suite (aka distrorelease)")

    parser.add_option("-d", "--dest-distro", type="string", metavar="DISTRO",
                      default=OUR_DISTRO,
                      help="Destination distribution")
    parser.add_option("-s", "--dest-suite", type="string", metavar="SUITE",
                      default=OUR_DIST,
                      help="Destination suite (aka distrorelease)")

    parser.add_option("-c", "--component", type="string", metavar="COMPONENT",
                      action="append",
                      help="Process only these destination components")

def main(options, args):
    src_distro = options.source_distro
    src_dist = options.source_suite

    our_distro = options.dest_distro
    our_dist = options.dest_suite

    # For each package in the destination distribution, find out whether
    # there's an open merge, and if so add an entry to the table for it.
    for our_component in DISTROS[our_distro]["components"]:
        if options.component is not None \
               and our_component not in options.component:
            continue

        merges = []

        for our_source in get_sources(our_distro, our_dist, our_component):
            try:
                package = our_source["Package"]
                our_version = Version(our_source["Version"])
                our_pool_source = get_pool_source(our_distro, package,
                                                  our_version)
                logging.debug("%s: %s is %s", package, our_distro, our_version)
            except IndexError:
                continue

            try:
                (src_source, src_version, src_pool_source) \
                             = get_same_source(src_distro, src_dist, package)
                logging.debug("%s: %s is %s", package, src_distro, src_version)
            except IndexError:
                continue

            try:
                base = get_base(our_pool_source)
                base_source = get_nearest_source(package, base)
                base_version = Version(base_source["Version"])
                logging.debug("%s: base is %s (%s wanted)",
                              package, base_version, base)
                continue
            except IndexError:
                pass

            priority_idx = PRIORITY.index(adjusted_priority(our_source))

            filename = changes_file(our_distro, our_source)
            if os.path.isfile(filename):
                changes = open(filename)
            elif os.path.isfile(filename + ".bz2"):
                changes = bz2.BZ2File(filename + ".bz2")
            else:
                changes = None

            if changes is not None:
                info = ControlFile(fileobj=changes,
                                   multi_para=False, signed=False).para

                user = info["Changed-By"]
                uploaded = info["Distribution"] == OUR_DIST
            else:
                user = None
                uploaded = False

            uploader = get_uploader(our_distro, our_source)

            if uploaded:
                section = "updated"
            else:
                section = "new"

            merges.append((section, priority_idx, package, user, uploader,
                           our_source, our_version, src_version))

        write_status_page(our_component, merges, our_distro, src_distro)
        write_status_json(our_component, merges, our_distro, src_distro)

        status_file = "%s/merges/tomerge-%s-manual" % (ROOT, our_component)
        remove_old_comments(status_file, merges)
        write_status_file(status_file, merges)


def write_status_page(component, merges, left_distro, right_distro):
    """Write out the manual merge status page."""
    merges.sort()

    status_file = "%s/merges/%s-manual.html" % (ROOT, component)
    with open(status_file + ".new", "w") as status:
        print("<html>", file=status)
        print(file=status)
        print("<head>", file=status)
        print("<meta http-equiv=\"Content-Type\" content=\"text/html; charset=utf-8\">", file=status)
        print("<title>Ubuntu Merge-o-Matic: %s manual</title>" % component,
              file=status)
        print("<style>", file=status)
        print("img#ubuntu {", file=status)
        print("    border: 0;", file=status)
        print("}", file=status)
        print("h1 {", file=status)
        print("    padding-top: 0.5em;", file=status)
        print("    font-family: sans-serif;", file=status)
        print("    font-size: 2.0em;", file=status)
        print("    font-weight: bold;", file=status)
        print("}", file=status)
        print("h2 {", file=status)
        print("    padding-top: 0.5em;", file=status)
        print("    font-family: sans-serif;", file=status)
        print("    font-size: 1.5em;", file=status)
        print("    font-weight: bold;", file=status)
        print("}", file=status)
        print("p, td {", file=status)
        print("    font-family: sans-serif;", file=status)
        print("    margin-bottom: 0;", file=status)
        print("}", file=status)
        print("li {", file=status)
        print("    font-family: sans-serif;", file=status)
        print("    margin-bottom: 1em;", file=status)
        print("}", file=status)
        print("tr.first td {", file=status)
        print("    border-top: 2px solid white;", file=status)
        print("}", file=status)
        print("</style>", file=status)
        print("<% from momlib import * %>", file=status)
        print("</head>", file=status)
        print("<body>", file=status)
        print("<img src=\".img/ubuntulogo-100.png\" id=\"ubuntu\">",
              file=status)
        print("<h1>Ubuntu Merge-o-Matic: %s manual</h1>" % component,
              file=status)

        for section in SECTIONS:
            section_merges = [ m for m in merges if m[0] == section ]
            print("<p><a href=\"#%s\">%s %s merges</a></p>" %
                  (section, len(section_merges), section), file=status)

        print("<% comment = get_comments() %>", file=status)

        for section in SECTIONS:
            section_merges = [ m for m in merges if m[0] == section ]

            print("<h2 id=\"%s\">%s Merges</h2>" % (section, section.title()),
                  file=status)

            do_table(status, section_merges, left_distro, right_distro, component)

        print("<p><small>Generated at %s.</small></p>" %
              time.strftime('%Y-%m-%d %H:%M:%S %Z'), file=status)
        print("</body>", file=status)
        print("</html>", file=status)

    os.rename(status_file + ".new", status_file)

def get_uploader(distro, source):
    """Obtain the uploader from the dsc file signature."""
    for md5sum, size, name in files(source):
        if name.endswith(".dsc"):
            dsc_file = name
            break
    else:
        return None

    filename = "%s/pool/%s/%s/%s/%s" \
            % (ROOT, distro, pathhash(source["Package"]), source["Package"], 
               dsc_file)

    (a, b, c) = os.popen3("gpg --verify %s" % filename)
    stdout = c.readlines()
    try:
        return stdout[1].split("Good signature from")[1].strip().strip("\"")
    except IndexError:
        return None

def do_table(status, merges, left_distro, right_distro, component):
    """Output a table."""
    print("<table cellspacing=0>", file=status)
    print("<tr bgcolor=#d0d0d0>", file=status)
    print("<td rowspan=2><b>Package</b></td>", file=status)
    print("<td colspan=2><b>Last Uploader</b></td>", file=status)
    print("<td rowspan=2><b>Comment</b></td>", file=status)
    print("<td rowspan=2><b>Bug</b></td>", file=status)
    print("</tr>", file=status)
    print("<tr bgcolor=#d0d0d0>", file=status)
    print("<td><b>%s Version</b></td>" % left_distro.title(), file=status)
    print("<td><b>%s Version</b></td>" % right_distro.title(), file=status)
    print("</tr>", file=status)

    for uploaded, priority, package, user, uploader, source, \
            left_version, right_version in merges:
        if user is not None:
            who = user
            who = who.replace("&", "&amp;")
            who = who.replace("<", "&lt;")
            who = who.replace(">", "&gt;")

            if uploader is not None:
                (usr_name, usr_mail) = parseaddr(user)
                (upl_name, upl_mail) = parseaddr(uploader)

                if len(usr_name) and usr_name != upl_name:
                    u_who = uploader
                    u_who = u_who.replace("&", "&amp;")
                    u_who = u_who.replace("<", "&lt;")
                    u_who = u_who.replace(">", "&gt;")

                    who = "%s<br><small><em>Uploader:</em> %s</small>" \
                            % (who, u_who)
        else:
            who = "&nbsp;"

        print("<tr bgcolor=%s class=first>" % COLOURS[priority], file=status)
        print("<td><tt><a href=\"https://patches.ubuntu.com/" \
              "%s/%s/%s_%s.patch\">%s</a></tt>" \
              % (pathhash(package), package, package, left_version, package),
              file=status)
        print(" <sup><a href=\"https://launchpad.net/ubuntu/" \
              "+source/%s\">LP</a></sup>" % package, file=status)
        print(" <sup><a href=\"http://packages.qa.debian.org/" \
              "%s\">PTS</a></sup></td>" % package, file=status)
        print("<td colspan=2>%s</td>" % who, file=status)
        print("<td rowspan=2><form method=\"get\" action=\"addcomment.py\"><br />",
              file=status)
        print("<input type=\"hidden\" name=\"component\" value=\"%s-manual\" />" % component,
              file=status)
        print("<input type=\"hidden\" name=\"package\" value=\"%s\" />" % package,
              file=status)
        print("<%%\n\
the_comment = \"\"\n\
if \"%s\" in comment:\n\
    the_comment = comment[\"%s\"]\n\
req.write(\"<input type=\\\"text\\\" style=\\\"border-style: none; background-color: %s\\\" name=\\\"comment\\\" value=\\\"%%s\\\" title=\\\"%%s\\\" />\" %% (the_comment, the_comment))\n\
%%>" % (package, package, COLOURS[priority]), file=status)
        print("</form></td>", file=status)
        print("<td rowspan=2>", file=status)
        print("<%%\n\
if \"%s\" in comment:\n\
    req.write(\"%%s\" %% gen_buglink_from_comment(comment[\"%s\"]))\n\
else:\n\
    req.write(\"&nbsp;\")\n\
\n\
%%>" % (package, package), file=status)
        print("</td>", file=status)
        print("</tr>", file=status)
        print("<tr bgcolor=%s>" % COLOURS[priority], file=status)
        print("<td><small>%s</small></td>" % source["Binary"], file=status)
        print("<td>%s</td>" % left_version, file=status)
        print("<td>%s</td>" % right_version, file=status)
        print("</tr>", file=status)

    print("</table>", file=status)


def write_status_json(component, merges, left_distro, right_distro):
    """Write out the merge status JSON dump."""
    status_file = "%s/merges/%s-manual.json" % (ROOT, component)
    with open(status_file + ".new", "w") as status:
        # No json module available on merges.ubuntu.com right now, but it's
        # not that hard to do it ourselves.
        print('[', file=status)
        cur_merge = 0
        for uploaded, priority, package, user, uploader, source, \
                left_version, right_version in merges:
            print(' {', end=' ', file=status)
            # source_package, short_description, and link are for
            # Harvest (http://daniel.holba.ch/blog/?p=838).
            print('"source_package": "%s",' % package, end=' ', file=status)
            print('"short_description": "merge %s",' % right_version,
                  end=' ', file=status)
            print('"link": "https://merges.ubuntu.com/%s/%s/",' %
                  (pathhash(package), package), end=' ', file=status)
            print('"uploaded": "%s",' % uploaded, end=' ', file=status)
            print('"priority": "%s",' % priority, end=' ', file=status)
            if user is not None:
                who = user
                who = who.replace('\\', '\\\\')
                who = who.replace('"', '\\"')
                print('"user": "%s",' % who, end=' ', file=status)
                if uploader is not None:
                    (usr_name, usr_mail) = parseaddr(user)
                    (upl_name, upl_mail) = parseaddr(uploader)
                    if len(usr_name) and usr_name != upl_name:
                        u_who = uploader
                        u_who = u_who.replace('\\', '\\\\')
                        u_who = u_who.replace('"', '\\"')
                        print('"uploader": "%s",' % u_who, end=' ', file=status)
            binaries = re.split(', *', source["Binary"].replace('\n', ''))
            print('"binaries": [ %s ],' %
                  ', '.join(['"%s"' % b for b in binaries]),
                  end=' ', file=status)
            print('"left_version": "%s",' % left_version, end=' ', file=status)
            print('"right_version": "%s"' % right_version,
                  end=' ', file=status)
            cur_merge += 1
            if cur_merge < len(merges):
                print('},', file=status)
            else:
                print('}', file=status)
        print(']', file=status)

    os.rename(status_file + ".new", status_file)


def write_status_file(status_file, merges):
    """Write out the merge status file."""
    with open(status_file + ".new", "w") as status:
        for uploaded, priority, package, user, uploader, source, \
                left_version, right_version in merges:
            print("%s %s %s %s, %s, %s, %s"
                  % (package, priority,
                     left_version, right_version, user, uploader, uploaded),
                  file=status)

    os.rename(status_file + ".new", status_file)


if __name__ == "__main__":
    run(main, options, usage="%prog",
        description="output status of manual merges")

