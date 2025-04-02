#!/usr/bin/env python
# manual-status.py - output status of manual merges
#
# Copyright © 2008 - 2015 Canonical Ltd.
# Authors: Scott James Remnant <scott@ubuntu.com>,
#          Brian Murray <brian@ubuntu.com>
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


import bz2
import datetime
import json
import logging
import os
import re
import subprocess
import textwrap
import time
from email.utils import parseaddr

from deb.controlfile import ControlFile
from deb.version import Version
from momlib import (
    DISTROS,
    OUR_DIST,
    OUR_DISTRO,
    ROOT,
    SRC_DIST,
    SRC_DISTRO,
    changes_file,
    files,
    get_base,
    get_date_superseded,
    get_importance,
    get_nearest_source,
    get_person_lp_page,
    get_pool_source,
    get_responsible_team,
    get_same_source,
    get_sources,
    pathhash,
    proposed_package_version,
    read_blocklist,
    remove_old_comments,
    run,
)
from util import tree

COLOURS = [
    "#ff8080",
    "#ffb580",
    "#ffea80",
    "#dfff80",
    "#abff80",
    "#80ff8b",
    "#d0d0d0",
]

# Sections
SECTIONS = ["new", "updated"]


def options(parser):
    parser.add_option(
        "-D",
        "--source-distro",
        type="string",
        metavar="DISTRO",
        default=SRC_DISTRO,
        help="Source distribution",
    )
    parser.add_option(
        "-S",
        "--source-suite",
        type="string",
        metavar="SUITE",
        default=SRC_DIST,
        help="Source suite (aka distrorelease)",
    )

    parser.add_option(
        "-d",
        "--dest-distro",
        type="string",
        metavar="DISTRO",
        default=OUR_DISTRO,
        help="Destination distribution",
    )
    parser.add_option(
        "-s",
        "--dest-suite",
        type="string",
        metavar="SUITE",
        default=OUR_DIST,
        help="Destination suite (aka distrorelease)",
    )

    parser.add_option(
        "-c",
        "--component",
        type="string",
        metavar="COMPONENT",
        action="append",
        help="Process only these destination components",
    )


def main(options, args):
    src_distro = options.source_distro
    src_dist = options.source_suite

    our_distro = options.dest_distro
    our_dist = options.dest_suite

    blocklist = read_blocklist()

    # For each package in the destination distribution, find out whether
    # there's an open merge, and if so add an entry to the table for it.
    for our_component in DISTROS[our_distro]["components"]:
        if (
            options.component is not None
            and our_component not in options.component
        ):
            continue

        merges = []

        for our_source in get_sources(our_distro, our_dist, our_component):
            if our_source["Package"] in blocklist:
                continue
            try:
                package = our_source["Package"]
                our_version = Version(our_source["Version"])
                our_pool_source = get_pool_source(
                    our_distro,
                    package,
                    our_version,
                )
                logging.debug("%s: %s is %s", package, our_distro, our_version)
            except (OSError, IndexError):
                continue

            try:
                (src_source, src_version, src_pool_source) = get_same_source(
                    src_distro,
                    src_dist,
                    package,
                )
                logging.debug("%s: %s is %s", package, src_distro, src_version)
            except IndexError:
                continue

            base_version = None
            try:
                base = get_base(our_pool_source)
                base_source = get_nearest_source(package, base)
                base_version = Version(base_source["Version"])
                logging.debug(
                    "%s: base is %s (%s wanted)",
                    package,
                    base_version,
                    base,
                )
                continue
            except IndexError:
                pass

            teams = get_responsible_team(package)
            date_superseded = get_date_superseded(package, base_version)
            if not date_superseded:
                age = datetime.timedelta(0)
            else:
                age = datetime.datetime.utcnow() - date_superseded.replace(
                    tzinfo=None,
                )
            days_old = age.days

            filename = changes_file(our_distro, our_source)
            if os.path.isfile(filename):
                changes = open(filename)
            elif os.path.isfile(filename + ".bz2"):
                changes = bz2.BZ2File(filename + ".bz2")
            else:
                changes = None

            if changes is not None:
                info = ControlFile(
                    fileobj=changes,
                    multi_para=False,
                    signed=False,
                ).para

                user = info.get("Changed-By") if info else None
                # not enough to determine if it is updated LP: #1474139
                # uploaded = info["Distribution"] == OUR_DIST
                uploaded = False
            else:
                user = None
                uploaded = False

            uploader = get_uploader(our_distro, our_source)

            if uploaded:
                section = "updated"
            else:
                section = "new"

            merges.append(
                (
                    section,
                    days_old,
                    package,
                    user,
                    uploader,
                    our_source,
                    our_version,
                    src_version,
                    teams,
                ),
            )

        write_status_page(our_component, merges, our_distro, src_distro)
        write_status_json(our_component, merges, our_distro, src_distro)

        status_file = "%s/merges/tomerge-%s-manual" % (ROOT, our_component)
        remove_old_comments(status_file, merges)
        write_status_file(status_file, merges)


def write_status_page(component, merges, left_distro, right_distro):
    """Write out the manual merge status page."""
    merges.sort(reverse=True)

    status_file = "%s/merges/%s-manual.html" % (ROOT, component)
    with tree.AtomicFile(status_file, "wt") as status:
        print(
            f"""<!DOCTYPE html>
<html>
<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8">
<title>Ubuntu Merge-o-Matic: {component} manual</title>
<style>
img#ubuntu {{
    border: 0;
}}
h1 {{
    padding-top: 0.5em;
    font-family: sans-serif;
    font-size: 2.0em;
    font-weight: bold;
}}
h2 {{
    padding-top: 0.5em;
    font-family: sans-serif;
    font-size: 1.5em;
    font-weight: bold;
}}
p, td {{
    font-family: sans-serif;
    margin-bottom: 0;
}}
li {{
    font-family: sans-serif;
    margin-bottom: 1em;
}}
tr.first td {{
    border-top: 2px solid white;
}}
</style>
<%
import html
from momlib import *
%>
</head>
<body>
<img src="./.static/img/ubuntulogo-100.png" id="ubuntu">
<h1>Ubuntu Merge-o-Matic: {component} manual</h1>
              """,
            file=status,
        )

        for section in SECTIONS:
            section_merges = [m for m in merges if m[0] == section]
            print(
                f'<p><a href="#{section}">{len(section_merges)} {section} merges</a></p>',
                file=status,
            )

        print("<% comment = get_comments() %>", file=status)

        for section in SECTIONS:
            section_merges = [m for m in merges if m[0] == section]

            print(
                f'<h2 id="{section}">{section.title()} Merges</h2>',
                file=status,
            )

            do_table(
                status,
                section_merges,
                left_distro,
                right_distro,
                component,
            )

        git_describe = (
            subprocess.check_output(
                ["git", "describe", "--tags", "--always", "--dirty"],
                cwd=os.path.dirname(__file__),
            )
            .decode()
            .strip()
        )
        print(
            f"""
        <p><small>Generated at {time.strftime("%Y-%m-%d %H:%M:%S %Z")}, by
        <a href="https://code.launchpad.net/~ubuntu-core-dev/merge-o-matic/+git/main">Merge-O-Matic</a> version {git_describe}.</small></p>
        </body>
        </html>
              """,
            file=status,
        )


def get_uploader(distro, source):
    """Obtain the uploader from the dsc file signature."""
    for _, name in files(source):
        if name.endswith(".dsc"):
            dsc_file = name
            break
    else:
        return None

    filename = "%s/pool/%s/%s/%s/%s" % (
        ROOT,
        distro,
        pathhash(source["Package"]),
        source["Package"],
        dsc_file,
    )

    with open(os.devnull, "w") as devnull:
        gpg = subprocess.Popen(
            ["gpg", "--verify", filename],
            stdout=devnull,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
    stderr = gpg.communicate()[1]
    if gpg.returncode != 0:
        return None
    for line in stderr.splitlines():
        if "Good signature from" in line:
            return line.split("Good signature from")[1].strip().strip('"')
    return None


def do_table(status, merges, left_distro, right_distro, component):
    """Output a table."""
    print(
        f"""
    <table cellspacing=0>
    <tr bgcolor=#d0d0d0>
    <td rowspan=2><b>Package [Responsible Teams]</b></td>
    <td colspan=3><b>Last Uploader</b></td>
    <td rowspan=2><b>Comment</b></td>
    <td rowspan=2><b>Bug</b></td>
    <td rowspan=2><b>Days Old</b></td>
    </tr>
    <tr bgcolor=#d0d0d0>
    <td><b>{left_distro.title()} Version</b></td>
    <td><b>{right_distro.title()} Version</b></td>
    <td><b>Base Version</b></td>
    </tr>
          """,
        file=status,
    )

    for (
        uploaded,
        age,
        package,
        user,
        uploader,
        source,
        left_version,
        right_version,
        teams,
    ) in merges:
        colour_idx = get_importance(age)
        if user is not None:
            (usr_name, usr_mail) = parseaddr(user)
            user_lp_page = get_person_lp_page(usr_mail)
            user = user.replace("&", "&amp;")
            user = user.replace("<", "&lt;")
            user = user.replace(">", "&gt;")
            if user_lp_page:
                who = "<a href='%s'>%s</a>" % (user_lp_page, user)
            else:
                who = user

            if uploader is not None:
                (upl_name, upl_mail) = parseaddr(uploader)
                upl_lp_page = get_person_lp_page(upl_mail)

                if usr_name and usr_name != upl_name:
                    u_who = uploader
                    u_who = u_who.replace("&", "&amp;")
                    u_who = u_who.replace("<", "&lt;")
                    u_who = u_who.replace(">", "&gt;")
                    if upl_lp_page:
                        who = (
                            "%s<br><small><em>Uploader:</em> "
                            "<a href='%s'>%s</a></small>"
                            % (who, upl_lp_page, u_who)
                        )
                    else:
                        who = "%s<br><small><em>Uploader:</em> %s</small>" % (
                            who,
                            u_who,
                        )
        else:
            who = "&nbsp;"

        if left_distro == "ubuntu":
            proposed_version = proposed_package_version(package, left_version)
        else:
            proposed_version = None
        if proposed_version:
            # If there is a proposed verison we want to set the bg colour to
            # grey and display the version number.
            colour_idx = 6

        print(
            f"""
        <tr bgcolor={COLOURS[colour_idx]} class=first>
            <td>
                <tt><a href="https://patches.ubuntu.com/{pathhash(package)}/{package}/{package}_{left_version}.patch">{package}</a></tt>
                <sup><a href="https://launchpad.net/ubuntu/+source/{package}">LP</a></sup>
                <sup><a href="https://tracker.debian.org/{package}">PTS</a></sup>
              """,
            file=status,
        )
        cell_data = ""
        if teams:
            cell_data += "["
            cell_data += "%s" % ", ".join(t for t in teams)
            cell_data += "]</td>"
        else:
            cell_data = "</td>"
        print(cell_data, file=status)

        print(
            f"""
              <td colspan=2>{who}</td>
              <td rowspan=2>
                  <form method="get" action="addcomment.py"><br />
                      <input type="hidden" name="component" value="{component}-manual" />
                      <input type="hidden" name="package" value="{package}" />
              """,
            file=status,
        )
        print(
            # The `start block` and `end block` are used to prevent mod_python's
            # PSP handler from getting confused with the indentation.
            # See https://modpython.org/live/current/doc-html/pythonapi.html#pyapi-psp
            # for some details.
            textwrap.dedent(
                f"""\
                <%
                # start block
                the_comment = ""
                the_color = "white"
                if "{package}" in comment:
                    the_comment = comment["{package}"]
                    the_color = "{COLOURS[colour_idx]}"
                req.write(
                    "<input type=\\"text\\" "
                    "style=\\"border-style: none; background-color: %s\\" "
                    "name=\\"comment\\" value=\\"%s\\" title=\\"%s\\" />" %
                    (the_color, html.escape(the_comment, quote=True),
                     html.escape(the_comment))
                )
                # end block
                %>
                """
            ),
            file=status,
        )
        print(
            """
            </form></td>
            <td rowspan=2>
            """,
            file=status,
        )
        print(
            textwrap.dedent(
                f"""
                <%
                # start block
                if "{package}" in comment:
                    req.write("%s" % gen_buglink_from_comment(comment["{package}"]))
                else:
                    req.write("&nbsp;")
                # end block
                %>"""
            ),
            file=status,
        )
        print(
            f"""
            </td>
            <td rowspan=2>
            {age}
            </td>
            </tr>
            <tr bgcolor="{COLOURS[colour_idx]}">
              """,
            file=status,
        )
        # If the given package list is more than 10, hide it
        if len(source["Binary"].strip().split(", ")) > 10:
            print(
                f"<td><small class='expanded'>{source['Binary']}</small></td>",
                file=status,
            )
        else:
            print(f"<td><small>{source['Binary']}</small></td>", file=status)
        if proposed_version:
            excuses_url = (
                "https://ubuntu-archive-team.ubuntu.com/"
                "proposed-migration/update_excuses.html"
            )
            print(
                f'<td>{left_version} (<a href="{excuses_url}#{package}">{proposed_version}</a>)</td>',
                file=status,
            )
        else:
            print(f"<td>{left_version}</td>", file=status)
        print(
            f"""
              <td>{right_version}</td>
              </tr>
              """,
            file=status,
        )

    print("</table>", file=status)


def write_status_json(component, merges, left_distro, right_distro):
    """Write out the merge status JSON dump."""
    status_file = "%s/merges/%s-manual.json" % (ROOT, component)
    data = []
    for (
        uploaded,
        age,
        package,
        user,
        uploader,
        source,
        left_version,
        right_version,
        teams,
    ) in merges:
        who = None
        u_who = None
        if user is not None:
            who = user
            who = who.replace("\\", "\\\\")
            who = who.replace('"', '\\"')
            if uploader is not None:
                (usr_name, usr_mail) = parseaddr(user)
                (upl_name, upl_mail) = parseaddr(uploader)
                if usr_name and usr_name != upl_name:
                    u_who = uploader
                    u_who = u_who.replace("\\", "\\\\")
                    u_who = u_who.replace('"', '\\"')
        binaries = re.split(", *", source["Binary"].replace("\n", ""))
        # source_package, short_description, and link are for
        # Harvest (http://daniel.holba.ch/blog/?p=838).
        data.append(
            {
                "source_package": package,
                "short_description": "merge %s" % right_version,
                "link": "https://merges.ubuntu.com/%s/%s/"
                % (pathhash(package), package),
                "uploaded": uploaded,
                "age": age,
                "user": who,
                "uploader": u_who,
                "binaries": binaries,
                "left_version": "%s" % left_version,
                "right_version": "%s" % right_version,
            },
        )
    with tree.AtomicFile(status_file, "wt") as status:
        status.write(json.dumps(data, indent=4))


def write_status_file(status_file, merges):
    """Write out the merge status file."""
    with tree.AtomicFile(status_file, "wt") as status:
        for (
            uploaded,
            age,
            package,
            user,
            uploader,
            source,
            left_version,
            right_version,
            teams,
        ) in merges:
            print(
                "%s %s %s %s, %s, %s, %s"
                % (
                    package,
                    age,
                    left_version,
                    right_version,
                    user,
                    uploader,
                    uploaded,
                ),
                file=status,
            )


if __name__ == "__main__":
    run(
        main,
        options,
        usage="%prog",
        description="output status of manual merges",
    )
