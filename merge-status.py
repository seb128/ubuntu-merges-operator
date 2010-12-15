#!/usr/bin/env python
# -*- coding: utf-8 -*-
# merge-status.py - output merge status
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
import bz2
import sys
import glob
import fcntl

from rfc822 import parseaddr
from momlib import *


# Order of priorities
PRIORITY = [ "unknown", "required", "important", "standard", "optional",
             "extra" ]
COLOURS =  [ "#ff8080", "#ffb580", "#ffea80", "#dfff80", "#abff80", "#80ff8b" ]

# Sections
SECTIONS = [ "outstanding", "new", "updated" ]


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

    outstanding = []
    if os.path.isfile("%s/outstanding-merges.txt" % ROOT):
        after_uvf = True

        f = open("%s/outstanding-merges.txt" % ROOT)
        try:
            for line in f:
                outstanding.append(line.strip())
        finally:
            f.close()
    else:
        after_uvf = False
        SECTIONS.remove("new")

    # For each package in the destination distribution, find out whether
    # there's an open merge, and if so add an entry to the table for it.
    for our_component in DISTROS[our_distro]["components"]:
        if options.component is not None \
               and our_component not in options.component:
            continue

        merges = []

        for source in get_sources(our_distro, our_dist, our_component):
            try:
                output_dir = result_dir(source["Package"])
                (base_version, left_version, right_version) \
                               = read_report(output_dir,
                                             our_distro, src_distro)
            except ValueError:
                continue

            try:
                priority_idx = PRIORITY.index(source["Priority"])
            except KeyError:
                priority_idx = 0

            filename = changes_file(our_distro, source)
            if os.path.isfile(filename):
                changes = open(filename)
            elif os.path.isfile(filename + ".bz2"):
                changes = bz2.BZ2File(filename + ".bz2")
            else:
                changes = None

            if changes is not None:
                info = ControlFile(fileobj=changes,
                                   multi_para=False, signed=False).para

                try:
                    user = info["Changed-By"]
                except KeyError:
                    user = None
                try:
                    uploaded = info["Distribution"] == OUR_DIST
                except KeyError:
                    uploaded = False
            else:
                user = None
                uploaded = False

            uploader = get_uploader(our_distro, source)

            if uploaded:
                section = "updated"
            elif not after_uvf:
                section = "outstanding"
            elif source["Package"] in outstanding:
                section = "outstanding"
            else:
                section = "new"

            merges.append((section, priority_idx, source["Package"], user,
                           uploader, source, base_version,
                           left_version, right_version))

        merges.sort()

        write_status_page(our_component, merges, our_distro, src_distro)
        write_status_json(our_component, merges, our_distro, src_distro)

        status_file = "%s/merges/tomerge-%s" % (ROOT, our_component)
        remove_old_comments(status_file, merges)
        write_status_file(status_file, merges)


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


def write_status_page(component, merges, left_distro, right_distro):
    """Write out the merge status page."""
    status_file = "%s/merges/%s.html" % (ROOT, component)
    status = open(status_file + ".new", "w")
    try:
        print >>status, "<html>"
        print >>status
        print >>status, "<head>"
        print >>status, "<meta http-equiv=\"Content-Type\" content=\"text/html; charset=utf-8\">"
        print >>status, "<title>Ubuntu Merge-o-Matic: %s</title>" % component
        print >>status, "<style>"
        print >>status, "img#ubuntu {"
        print >>status, "    border: 0;"
        print >>status, "}"
        print >>status, "h1 {"
        print >>status, "    padding-top: 0.5em;"
        print >>status, "    font-family: sans-serif;"
        print >>status, "    font-size: 2.0em;"
        print >>status, "    font-weight: bold;"
        print >>status, "}"
        print >>status, "h2 {"
        print >>status, "    padding-top: 0.5em;"
        print >>status, "    font-family: sans-serif;"
        print >>status, "    font-size: 1.5em;"
        print >>status, "    font-weight: bold;"
        print >>status, "}"
        print >>status, "p, td {"
        print >>status, "    font-family: sans-serif;"
        print >>status, "    margin-bottom: 0;"
        print >>status, "}"
        print >>status, "li {"
        print >>status, "    font-family: sans-serif;"
        print >>status, "    margin-bottom: 1em;"
        print >>status, "}"
        print >>status, "tr.first td {"
        print >>status, "    border-top: 2px solid white;"
        print >>status, "}"
        print >>status, "</style>"
        print >>status, "<% from momlib import * %>"
        print >>status, "</head>"
        print >>status, "<body>"
        print >>status, "<img src=\".img/ubuntulogo-100.png\" id=\"ubuntu\">"
        print >>status, "<h1>Ubuntu Merge-o-Matic: %s</h1>" % component

        for section in SECTIONS:
            section_merges = [ m for m in merges if m[0] == section ]
            print >>status, ("<p><a href=\"#%s\">%s %s merges</a></p>"
                             % (section, len(section_merges), section))

        print >>status, "<ul>"
        print >>status, ("<li>If you are not the previous uploader, ask the "
                         "previous uploader before doing the merge.  This "
                         "prevents two people from doing the same work.</li>")
        print >>status, ("<li>Before uploading, update the changelog to "
                         "have your name and a list of the outstanding "
                         "Ubuntu changes.</li>")
        print >>status, ("<li>Try and keep the diff small, this may involve "
                         "manually tweaking <tt>po</tt> files and the "
                         "like.</li>")
        print >>status, "</ul>"

        print >>status, "<% comment = get_comments() %>"

        for section in SECTIONS:
            section_merges = [ m for m in merges if m[0] == section ]

            print >>status, ("<h2 id=\"%s\">%s Merges</h2>"
                             % (section, section.title()))

            do_table(status, section_merges, left_distro, right_distro, component)

        print >>status, "<h2 id=stats>Statistics</h2>"
        print >>status, ("<img src=\"%s-now.png\" title=\"Current stats\">"
                         % component)
        print >>status, ("<img src=\"%s-trend.png\" title=\"Six month trend\">"
                         % component)
        print >>status, "</body>"
        print >>status, "</html>"
    finally:
        status.close()

    os.rename(status_file + ".new", status_file)

def do_table(status, merges, left_distro, right_distro, component):
    """Output a table."""
    print >>status, "<table cellspacing=0>"
    print >>status, "<tr bgcolor=#d0d0d0>"
    print >>status, "<td rowspan=2><b>Package</b></td>"
    print >>status, "<td colspan=3><b>Last Uploader</b></td>"
    print >>status, "<td rowspan=2><b>Comment</b></td>"
    print >>status, "<td rowspan=2><b>Bug</b></td>"
    print >>status, "</tr>"
    print >>status, "<tr bgcolor=#d0d0d0>"
    print >>status, "<td><b>%s Version</b></td>" % left_distro.title()
    print >>status, "<td><b>%s Version</b></td>" % right_distro.title()
    print >>status, "<td><b>Base Version</b></td>"
    print >>status, "</tr>"

    for uploaded, priority, package, user, uploader, source, \
            base_version, left_version, right_version in merges:
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

        print >>status, "<tr bgcolor=%s class=first>" % COLOURS[priority]
        print >>status, "<td><tt><a href=\"%s/%s/REPORT\">" \
              "%s</a></tt>" % (pathhash(package), package, package)
        print >>status, " <sup><a href=\"https://launchpad.net/ubuntu/" \
              "+source/%s\">LP</a></sup>" % package
        print >>status, " <sup><a href=\"http://packages.qa.debian.org/" \
              "%s\">PTS</a></sup></td>" % package
        print >>status, "<td colspan=3>%s</td>" % who
        print >>status, "<td rowspan=2><form method=\"get\" action=\"addcomment.py\"><br />"
        print >>status, "<input type=\"hidden\" name=\"component\" value=\"%s\" />" % component
        print >>status, "<input type=\"hidden\" name=\"package\" value=\"%s\" />" % package
        print >>status, "<%%\n\
the_comment = \"\"\n\
if(comment.has_key(\"%s\")):\n\
    the_comment = comment[\"%s\"]\n\
req.write(\"<input type=\\\"text\\\" style=\\\"border-style: none; background-color: %s\\\" name=\\\"comment\\\" value=\\\"%%s\\\" title=\\\"%%s\\\" />\" %% (the_comment, the_comment))\n\
%%>" % (package, package, COLOURS[priority])
        print >>status, "</form></td>"
        print >>status, "<td rowspan=2>"
        print >>status, "<%%\n\
if(comment.has_key(\"%s\")):\n\
    req.write(\"%%s\" %% gen_buglink_from_comment(comment[\"%s\"]))\n\
else:\n\
    req.write(\"&nbsp;\")\n\
\n\
%%>" % (package, package)
        print >>status, "</td>"
        print >>status, "</tr>"
        print >>status, "<tr bgcolor=%s>" % COLOURS[priority]
        print >>status, "<td><small>%s</small></td>" % source["Binary"]
        print >>status, "<td>%s</td>" % left_version
        print >>status, "<td>%s</td>" % right_version
        print >>status, "<td>%s</td>" % base_version
        print >>status, "</tr>"

    print >>status, "</table>"


def write_status_json(component, merges, left_distro, right_distro):
    """Write out the merge status JSON dump."""
    status_file = "%s/merges/%s.json" % (ROOT, component)
    status = open(status_file + ".new", "w")
    # No json module available on merges.ubuntu.com right now, but it's not
    # that hard to do it ourselves.
    try:
        print >>status, '['
        for section in SECTIONS:
            for uploaded, priority, package, user, uploader, source, \
                    base_version, left_version, right_version in merges:
                print >>status, ' { ',
                # source_package, short_description, and link are for
                # Harvest (http://daniel.holba.ch/blog/?p=838).
                print >>status, '"source_package": "%s", ' % package,
                print >>status, '"short_description": "merge %s", ' % right_version,
                print >>status, '"link": "https://merges.ubuntu.com/%s/%s/", ' % (pathhash(package), package),
                print >>status, '"section": "%s", ' % section
                print >>status, '"uploaded": %s, ' % ("true" if uploaded else "false"),
                print >>status, '"priority": "%s", ' % priority,
                if user is not None:
                    who = user
                    who = who.replace('\\', '\\\\')
                    who = who.replace('"', '\\"')
                    print >>status, '"user": "%s", ' % who,
                    if uploader is not None:
                        u_who = uploader
                        u_who = u_who.replace('\\', '\\\\')
                        u_who = u_who.replace('"', '\\"')
                        print >>status, '"uploader": "%s", ' % u_who,
                binaries = source["Binary"].split(', ')
                print >>status, '"binaries": [ %s ], ' % \
                                ', '.join(['"%s"' % b for b in binaries]),
                print >>status, '"base_version": "%s", ' % base_version,
                print >>status, '"left_version": "%s", ' % left_version,
                print >>status, '"right_version": "%s"' % right_version,
                print >>status, ' }'
        print >>status, ']'
    finally:
        status.close()

    os.rename(status_file + ".new", status_file)


def write_status_file(status_file, merges):
    """Write out the merge status file."""
    status = open(status_file + ".new", "w")
    try:
        for uploaded, priority, package, user, uploader, source, \
                base_version, left_version, right_version in merges:
            print >>status, "%s %s %s %s %s %s, %s, %s" \
                  % (package, priority, base_version,
                     left_version, right_version, user, uploader, uploaded)
    finally:
        status.close()

    os.rename(status_file + ".new", status_file)

if __name__ == "__main__":
    run(main, options, usage="%prog",
        description="output merge status")

