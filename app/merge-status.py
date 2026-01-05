#!/usr/bin/python3
# merge-status.py - output merge status
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
from datetime import timezone
import json
import os
import re
import subprocess
import textwrap
import time
from email.utils import parseaddr

from deb.controlfile import ControlFile
from momlib import (
    DISTROS,
    OUR_DIST,
    OUR_DISTRO,
    ROOT,
    SRC_DIST,
    SRC_DISTRO,
    changes_file,
    files,
    get_date_superseded,
    get_importance,
    get_person_lp_page,
    get_responsible_team,
    get_sources,
    pathhash,
    proposed_package_version,
    read_blocklist,
    read_report,
    remove_old_comments,
    result_dir,
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
SECTIONS = ["outstanding", "new", "updated"]


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
    now = datetime.datetime.now(timezone.utc)

    src_distro = options.source_distro

    our_distro = options.dest_distro
    our_dist = options.dest_suite

    blocklist = read_blocklist()

    outstanding = []
    if os.path.isfile("%s/outstanding-merges.txt" % ROOT):
        after_uvf = True

        with open("%s/outstanding-merges.txt" % ROOT) as f:
            for line in f:
                outstanding.append(line.strip())
    else:
        after_uvf = False
        SECTIONS.remove("new")

    # For each package in the destination distribution, find out whether
    # there's an open merge, and if so add an entry to the table for it.
    for our_component in DISTROS[our_distro]["components"]:
        if (
            options.component is not None
            and our_component not in options.component
        ):
            continue

        merges = []

        for source in get_sources(our_distro, our_dist, our_component):
            if source["Package"] in blocklist:
                continue
            try:
                output_dir = result_dir(source["Package"])
                (base_version, left_version, right_version) = read_report(
                    output_dir,
                    our_distro,
                    src_distro,
                )
            except ValueError:
                continue
            teams = get_responsible_team(source["Package"])
            date_superseded = get_date_superseded(
                source["Package"],
                base_version,
            )
            if not date_superseded:
                age = datetime.timedelta(0)
            else:
                ds_aware = date_superseded.replace(tzinfo=timezone.utc)
                age = now - ds_aware

            days_old = age.days

            filename = changes_file(our_distro, source)
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
                try:
                    uploaded = False
                    # not enough to determine if it is updated LP: #1474139
                    # uploaded = info["Distribution"] == OUR_DIST
                    # better but not sufficient
                    # if info["Distribution"] == OUR_DIST:
                    #     if base_version.upstream == left_version.upstream:
                    #         uploaded = True
                except KeyError:
                    uploaded = False
            else:
                user = None
                uploaded = False

            uploader = get_uploader(our_distro, source)

            if uploaded:
                section = "updated"
            elif not after_uvf or source["Package"] in outstanding:
                section = "outstanding"
            else:
                section = "new"

            merges.append(
                (
                    section,
                    days_old,
                    source["Package"],
                    user,
                    uploader,
                    source,
                    base_version,
                    left_version,
                    right_version,
                    teams,
                ),
            )
        merges.sort(reverse=True)

        write_status_page(our_component, merges, our_distro, src_distro)
        write_status_json(our_component, merges, our_distro, src_distro)

        status_file = "%s/merges/tomerge-%s" % (ROOT, our_component)
        remove_old_comments(status_file, merges)
        write_status_file(status_file, merges)


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

def write_status_page(component, merges, left_distro, right_distro):
    """Write out the merge status page."""
    status_file = "%s/merges/%s.html" % (ROOT, component)

    try:
        from pathlib import Path
        agent_dir = Path("/var/lib/juju/agents/")
        # Finds the first directory matching the pattern
        charm_dir = next(agent_dir.glob("unit-ubuntu-merges-*")) / "charm"
        revision = (charm_dir / "version").read_text().strip()
    except (StopIteration, FileNotFoundError, PermissionError):
        revision = "unknown"

    now_str = datetime.datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    with tree.AtomicFile(status_file, "wt") as status:
        print(
            f"""<!DOCTYPE html>
<html>
<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8">
<title>Ubuntu Merge-o-Matic: {component}</title>
<link href="https://fonts.googleapis.com/css?family=Ubuntu:300,400,500,700" rel="stylesheet">
<style>
    :root {{
        --ubuntu-orange: #e95420;
        --ubuntu-aubergine: #772953;
        --text-color: #1a1a1a;
        --bg-page: #f3f4f6;
    }}
    body {{
        font-family: "Ubuntu", sans-serif;
        background-color: var(--bg-page);
        color: var(--text-color);
        margin: 0;
        padding: 20px;
        line-height: 1.5;
    }}
    h1 {{
        color: var(--ubuntu-aubergine);
        border-bottom: 4px solid var(--ubuntu-orange);
        padding-bottom: 10px;
        margin-bottom: 30px;
    }}
    table {{
        width: 100%;
        border-collapse: separate;
        border-spacing: 0;
        background: white;
        border: 2px solid #9ca3af;
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
        border-radius: 8px;
        overflow: hidden;
    }}
    th {{
        background-color: #4b5563;
        color: white;
        text-align: left;
        padding: 15px;
        text-transform: uppercase;
        font-size: 0.85em;
        letter-spacing: 0.05em;
    }}
    td {{
        padding: 12px 15px;
        border-bottom: 1px solid rgba(0,0,0,0.1);
        vertical-align: top;
    }}
    tr.first td {{
        border-top: 2px solid #6b7280;
    }}
    input[type="text"] {{
        border: 1px solid #9ca3af !important;
        background-color: white !important;
        padding: 6px;
        border-radius: 3px;
        color: #000;
        width: 95%;
    }}
    a {{
        color: #c2410c;
        text-decoration: none;
        font-weight: bold;
    }}
    a:hover {{
        text-decoration: underline;
    }}
    .stats-container {{
        display: flex;
        flex-wrap: wrap;
        justify-content: space-between;
        align-items: flex-start;
        gap: 20px;
        margin-top: 30px;
        width: 100%;
    }}

    .stats-container img {{
        box-sizing: border-box;
        height: auto;
        border: 1px solid #ddd;
        border-radius: 4px;
        box-shadow: 0 1px 4px rgba(0,0,0,0.1);
        min-width: 300px;
    }}

    .stats-container img:first-child {{
        flex: 0 1 calc(30% - 10px);
    }}

    .stats-container img:last-child {{
        flex: 0 1 calc(70% - 10px);
    }}

    .expanded {{
        display: none;
    }}

    footer {{
        margin-top: 50px;
        padding: 20px 0;
        border-top: 1px solid #eee;
        font-size: 0.85rem;
        color: #333;
    }}
</style>
<%
import html
from momlib import *
%>
</head>
<body>
<div class="container">
    <img src="./.static/img/ubuntulogo-100.png" id="ubuntu" alt="Ubuntu Logo">
    <h1>Merge-o-Matic: {component}</h1>

    <div id="filters">
        <div style="margin-bottom: 10px;"><strong>Filters:</strong>
            <input id="query" name="query" style="width: 300px;"/>
        </div>
        <label><input id="showProposed" checked="checked" type="checkbox"> Show Proposed</label> &nbsp;
        <label><input id="showMergeNeeded" checked="checked" type="checkbox"> Show Merge Needed</label> &nbsp;
        <label><input id="showLongBinaries" type="checkbox"> Show full binary list</label>
    </div>

    <div id="navigation">
              """,
            file=status,
        )

        for section in SECTIONS:
            section_merges = [m for m in merges if m[0] == section]
            print(
                f'<a href="#{section}" style="margin-right: 15px;">&rarr; {len(section_merges)} {section} merges</a>',
                file=status,
            )

        print(
            """
    </div>

    <div style="background: #FFFBEB; border-left: 8px solid #F59E0B; padding: 20px; margin: 25px 0; color: #92400E; border-radius: 4px;">
        <strong style="font-size: 1.1em; letter-spacing: 0.5px;">Guidelines:</strong>
        <ul style="margin: 10px 0 0 0; padding-left: 20px; line-height: 1.6;">
            <li>If you are not the previous uploader, ask them before starting to avoid duplicated effort.</li>
            <li>Before uploading, update the changelog with your name and the list of outstanding Ubuntu changes.</li>
            <li>Try and keep the diff small, this may involve manually tweaking <tt>po</tt> files and the like.</li>
        </ul>
    </div>
    <% comment = get_comments() %>
              """,
            file=status,
        )

        for section in SECTIONS:
            section_merges = [m for m in merges if m[0] == section]
            print(f'<h2 id="{section}">{section.title()} Merges</h2>', file=status)
            do_table(status, section_merges, left_distro, right_distro, component)

        print(
            f"""
    <h2 id="stats">Statistics</h2>
    <div class="stats-container">
        <img src="{component}-now.png" alt="Current Statistics">
        <img src="{component}-trend.png" alt="Six Month Trend">
    </div>

    <footer>
        Generated at {now_str} by 
        <strong>merge-o-matic</strong> (revision {revision}).
    </footer>
</div>
              """,
            file=status,
        )

        print(
            textwrap.dedent(
                """
            <script type="text/javascript">
                (function() {
                    var query = document.getElementById("query");
                    var showProposed = document.getElementById("showProposed");
                    var showMergeNeeded = document.getElementById("showMergeNeeded");
                    var showLongBinaries = document.getElementById("showLongBinaries");

                    function filterText() {
                        var regexp = new RegExp(query.value, "i");
                        var tables = document.getElementsByTagName("table");
                        for (var t=0; t < tables.length; t++) {
                            var rows = tables[t].getElementsByTagName("tr");
                            for (var i=2; i < rows.length; i += 2)  {
                                var hide = (
                                    (query.value && !rows[i].textContent.match(regexp)) ||
                                    (!showProposed.checked && rows[i].bgColor === '#d0d0d0') ||
                                    (!showMergeNeeded.checked && rows[i].bgColor !== '#d0d0d0')
                                );
                                rows[i].hidden = rows[i+1].hidden = hide;
                            }
                        }
                        var long_lines = document.getElementsByClassName("expanded");
                        var show_binaries = showLongBinaries.checked ? "inline" : "none";
                        for (var i=0; i < long_lines.length; i++) {
                            long_lines[i].style.display = show_binaries;
                        }
                    }

                    query.addEventListener('input', filterText);
                    showProposed.addEventListener('change', filterText);
                    showMergeNeeded.addEventListener('change', filterText);
                    showLongBinaries.addEventListener('change', filterText);
                })();
            </script>
            </body>
            </html>
            """,
            ),
            file=status,
        )

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
        base_version,
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
                <tt><a href="{pathhash(package)}/{package}/REPORT">{package}</a></tt>
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
              <td colspan=3>{who}</td>
              <td rowspan=2>
                  <form method="get" action="addcomment.py"><br />
                      <input type="hidden" name="component" value="{component}" />
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
              <td>{base_version}</td>
              </tr>
              """,
            file=status,
        )

    print("</table>", file=status)


def write_status_json(component, merges, left_distro, right_distro):
    """Write out the merge status JSON dump."""
    status_file = "%s/merges/%s.json" % (ROOT, component)
    data = []
    for (
        uploaded,
        age,
        package,
        user,
        uploader,
        source,
        base_version,
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
                "teams": list(teams),
                "binaries": binaries,
                "base_version": "%s" % base_version,
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
            base_version,
            left_version,
            right_version,
            teams,
        ) in merges:
            print(
                "%s %s %s %s %s %s, %s, %s"
                % (
                    package,
                    age,
                    base_version,
                    left_version,
                    right_version,
                    user,
                    uploader,
                    uploaded,
                ),
                file=status,
            )


if __name__ == "__main__":
    run(main, options, usage="%prog", description="output merge status")
