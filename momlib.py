#!/usr/bin/env python
# -*- coding: utf-8 -*-
# momlib.py - common utility functions
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

from __future__ import print_function, with_statement

from cgi import escape
from collections import defaultdict
from contextlib import closing
import datetime
import errno
import fcntl
from hashlib import md5
import json
import logging
from optparse import OptionParser
import os
import re
import stat
import subprocess
import sys
import time
from xml.etree import ElementTree

try:
    from urllib.parse import quote
    from urllib.request import urlopen
except ImportError:
    from urllib import quote
    from urllib2 import urlopen

from launchpadlib.launchpad import Launchpad

from deb.controlfile import ControlFile
from deb.version import Version
from util import tree


# Output root
ROOT = "/srv/patches.ubuntu.com"

# Distribution definitions
DISTROS = {
    "ubuntu": {
        "mirror": "http://archive.ubuntu.com/ubuntu",
        "dists": ["oracular"],
        "components": ["main", "restricted", "universe", "multiverse"],
        "expire": True,
    },
    "debian": {
        "mirror": "http://ftp.uk.debian.org/debian",
        "dists": [
            "unstable",
            "testing",
            "testing-proposed-updates",
            "experimental",
        ],
        "components": ["main", "contrib", "non-free", "non-free-firmware"],
        "expire": True,
    },
    #    "dapper-security": {
    #        "mirror": "http://security.ubuntu.com/ubuntu",
    #        "dists": [ "dapper-security" ],
    #        "components": [ "main", "restricted", "universe", "multiverse" ],
    #        "expire": False,
    #        },
    #    "hardy-security": {
    #        "mirror": "http://security.ubuntu.com/ubuntu",
    #        "dists": [ "hardy-security" ],
    #        "components": [ "main", "restricted", "universe", "multiverse" ],
    #        "expire": False,
    #        },
    #    "intrepid-security": {
    #        "mirror": "http://security.ubuntu.com/ubuntu",
    #        "dists": [ "intrepid-security" ],
    #        "components": [ "main", "restricted", "universe", "multiverse" ],
    #        "expire": False,
    #        },
    #    "jaunty-security": {
    #        "mirror": "http://security.ubuntu.com/ubuntu",
    #        "dists": [ "jaunty-security" ],
    #        "components": [ "main", "restricted", "universe", "multiverse" ],
    #        "expire": False,
    #        },
}

# Destination distribution and release
OUR_DISTRO = "ubuntu"
OUR_DIST = "oracular"

# Default source distribution and release
SRC_DISTRO = "debian"
SRC_DIST = "unstable"


# Time format for RSS feeds
RSS_TIME_FORMAT = "%a, %d %b %Y %H:%M:%S %Z"


# Cache of parsed sources files
SOURCES_CACHE = {}

# mapping of uploader emails to Launchpad pages
person_lp_page_mapping = {}

# mapping of packages to teams
package_team_mapping = ""

# --------------------------------------------------------------------------- #
# Command-line tool functions
# --------------------------------------------------------------------------- #


def run(main_func, options_func=None, usage=None, description=None):
    """Run the given main function after initialising options."""
    logging.basicConfig()
    logging.getLogger().setLevel(logging.DEBUG)

    parser = OptionParser(usage=usage, description=description)
    parser.add_option(
        "-q",
        "--quiet",
        action="callback",
        callback=quiet_callback,
        help="Be less chatty",
    )
    if options_func is not None:
        options_func(parser)

    (options, args) = parser.parse_args()
    sys.exit(main_func(options, args))


def quiet_callback(opt, value, parser, *args, **kwds):
    logging.getLogger().setLevel(logging.WARNING)


# --------------------------------------------------------------------------- #
# Utility functions
# --------------------------------------------------------------------------- #


def ensure(path):
    """Ensure that the parent directories for path exist."""
    dirname = os.path.dirname(path)
    if not os.path.isdir(dirname):
        if os.path.islink(dirname) and not os.path.exists(dirname):
            # Broken symbolic link; create the target.
            os.makedirs(os.path.realpath(dirname))
        else:
            os.makedirs(dirname)


def pathhash(path):
    """Return the path hash component for path."""
    if path.startswith("lib"):
        return path[:4]
    else:
        return path[:1]


def cleanup(path):
    """Remove the path and any empty directories up to ROOT."""
    tree.remove(path)

    (dirname, basename) = os.path.split(path)
    while dirname != ROOT:
        try:
            os.rmdir(dirname)
        except OSError as e:
            if e.errno == errno.ENOTEMPTY or e.errno == errno.ENOENT:
                break
            # Stop if we reach a symlink, allowing the sometimes-large
            # ROOT/unpacked to be symlinked onto a separate filesystem.
            if e.errno == errno.ENOTDIR:
                break
            raise

        (dirname, basename) = os.path.split(dirname)


def md5sum(filename):
    """Return an md5sum."""
    return md5(open(filename).read()).hexdigest()


def get_person_lp_page(person_email):
    """Make a best guess at what the person's LP page is."""
    if person_email in person_lp_page_mapping:
        return person_lp_page_mapping[person_email]
    email = quote(person_email)
    find_person = (
        "https://api.launchpad.net/devel/people/?ws.op=findPerson&text=%s"
        % email
    )
    try:
        with closing(urlopen(find_person)) as response:
            content = response.read()
    except IOError:
        return None
    data = json.loads(content)["entries"]
    # findPerson does a startswith match so could return multiple entries, if
    # that happens return None as credentials are needed to confirm the email.
    if len(data) != 1:
        person_lp_page_mapping[person_email] = None
    else:
        person_lp_page = data[0]["web_link"]
        # This will only ever consist of ASCII, and on Python 2 it makes
        # life easier if we return str rather than unicode.
        if not isinstance(person_lp_page, str):
            person_lp_page = person_lp_page.encode("UTF-8")
        person_lp_page_mapping[person_email] = person_lp_page
    return person_lp_page_mapping[person_email]


def get_importance(days):
    "Return an int representing the importance of an item."
    if days <= 30:
        return 5
    elif days <= 60:
        return 4
    elif days <= 90:
        return 3
    elif days <= 180:
        return 2
    elif days <= 365:
        return 1
    return 0


def get_responsible_team(source_package):
    """Return teams, as a set, subscribed to a package using the package to
       team mapping."""
    global package_team_mapping
    if not package_team_mapping:
        package_team_mapping = defaultdict(set)
        mapping_file = "%s/code/package-team-mapping.json" % ROOT
        if os.path.exists(mapping_file):
            with open(mapping_file) as ptm_file:
                for team, packages in json.load(ptm_file).items():
                    if team == "unsubscribed":
                        continue
                    for package in packages:
                        package_team_mapping[package].add(team)
    if source_package in package_team_mapping:
        return package_team_mapping[source_package]
    else:
        return ""


def get_team_packages(team):
    """Return list of packages owned by a team."""
    if not team:
        return []

    mapping_file = "%s/code/package-team-mapping.json" % ROOT
    if os.path.exists(mapping_file):
        with open(mapping_file) as ptm_file:
            for fteam, packages in json.load(ptm_file).items():
                if team == fteam:
                    return packages

    return []


# --------------------------------------------------------------------------- #
# Location functions
# --------------------------------------------------------------------------- #


def sources_file(distro, dist, component):
    """Return the location of a local Sources file."""
    return "%s/dists/%s-%s/%s/source/Sources" % (ROOT, distro, dist, component)


def pool_directory(distro, package):
    """Return the pool directory for a source"""
    return "pool/%s/%s/%s" % (distro, pathhash(package), package)


def pool_sources_file(distro, package):
    """Return the location of a pool Sources file for a source."""
    pooldir = pool_directory(distro, package)
    return "%s/%s/Sources" % (ROOT, pooldir)


def unpack_directory(source):
    """Return the location of a local unpacked source."""
    return "%s/unpacked/%s/%s/%s" % (
        ROOT,
        pathhash(source["Package"]),
        source["Package"],
        source["Version"],
    )


def changes_file(distro, source):
    """Return the location of a local changes file."""
    return "%s/changes/%s/%s/%s/%s_%s_source.changes" % (
        ROOT,
        distro,
        pathhash(source["Package"]),
        source["Package"],
        source["Package"],
        source["Version"],
    )


def dpatch_directory(distro, source):
    """Return the directory where we put dpatches."""
    return "%s/dpatches/%s/%s/%s/%s" % (
        ROOT,
        distro,
        pathhash(source["Package"]),
        source["Package"],
        source["Version"],
    )


def diff_directory(distro, source):
    """Return the directory where we can find diffs."""
    return "%s/diffs/%s/%s/%s" % (
        ROOT,
        distro,
        pathhash(source["Package"]),
        source["Package"],
    )


def diff_file(distro, source):
    """Return the location of a local diff file."""
    return "%s/%s_%s.patch" % (
        diff_directory(distro, source),
        source["Package"],
        source["Version"],
    )


def patch_directory(distro, source):
    """Return the directory where we can find local patch files."""
    return "%s/patches/%s/%s/%s" % (
        ROOT,
        distro,
        pathhash(source["Package"]),
        source["Package"],
    )


def patch_file(distro, source, slipped=False):
    """Return the location of a local patch file."""
    path = "%s/%s_%s" % (
        patch_directory(distro, source),
        source["Package"],
        source["Version"],
    )
    if slipped:
        return path + ".slipped-patch"
    else:
        return path + ".patch"


def published_file(distro, source):
    """Return the location where published patches should be placed."""
    return "%s/published/%s/%s/%s_%s.patch" % (
        ROOT,
        pathhash(source["Package"]),
        source["Package"],
        source["Package"],
        source["Version"],
    )


def patch_list_file():
    """Return the location of the patch list."""
    return "%s/published/PATCHES" % ROOT


def patch_rss_file(distro=None, source=None):
    """Return the location of the patch rss feed."""
    if distro is None or source is None:
        return "%s/published/patches.xml" % ROOT
    else:
        return "%s/patches.xml" % patch_directory(distro, source)


def diff_rss_file(distro=None, source=None):
    """Return the location of the diff rss feed."""
    if distro is None or source is None:
        return "%s/diffs/patches.xml" % ROOT
    else:
        return "%s/patches.xml" % diff_directory(distro, source)


def work_dir(package, version):
    """Return the directory to produce the merge result."""
    return "%s/work/%s/%s/%s" % (ROOT, pathhash(package), package, version)


def result_dir(package):
    """Return the directory to store the result in."""
    return "%s/merges/%s/%s" % (ROOT, pathhash(package), package)


# --------------------------------------------------------------------------- #
# Sources file handling
# --------------------------------------------------------------------------- #


def get_sources(distro, dist, component):
    """Parse a cached Sources file."""
    global SOURCES_CACHE

    filename = sources_file(distro, dist, component)
    if filename not in SOURCES_CACHE:
        SOURCES_CACHE[filename] = ControlFile(
            filename, multi_para=True, signed=False
        )

    return SOURCES_CACHE[filename].paras


def get_source(distro, dist, component, package):
    """Return the source for a package in a distro."""
    sources = get_sources(distro, dist, component)
    matches = []
    for source in sources:
        if source["Package"] == package:
            matches.append(source)
    if matches:
        version_sort(matches)
        return matches.pop()
    else:
        raise IndexError


# --------------------------------------------------------------------------- #
# Pool handling
# --------------------------------------------------------------------------- #


def get_pool_distros():
    """Return the list of distros with pools."""
    return list(DISTROS)


def pool_sources_already_updated(pooldir, filename):
    try:
        ctime = os.stat(filename).st_ctime
    except OSError:
        return False

    poolpath = os.path.join(ROOT, pooldir)
    for otherfile in ["."] + os.listdir(poolpath):
        if otherfile in {"Sources", "watermark"}:
            continue
        try:
            st = os.stat(os.path.join(poolpath, otherfile))
            if st.st_mtime > ctime or st.st_ctime > ctime:
                return False
        except OSError:
            pass
    return True


def update_pool_sources(distro, package):
    """Update the Sources files in the pool."""
    pooldir = pool_directory(distro, package)
    filename = pool_sources_file(distro, package)
    if pool_sources_already_updated(pooldir, filename):
        return

    logging.info("Updating %s", tree.subdir(ROOT, filename))
    with tree.AtomicFile(filename) as sources:
        with open(os.devnull, "wb") as devnull:
            subprocess.check_call(
                ("apt-ftparchive", "sources", pooldir),
                cwd=ROOT,
                stdout=sources,
                stderr=devnull,
            )


def get_pool_sources(distro, package):
    """Parse the Sources file for a package in the pool."""
    filename = pool_sources_file(distro, package)
    sources = ControlFile(filename, multi_para=True, signed=False)
    return sources.paras


def get_pool_source(distro, package, version=None):
    """Return the source for a particular version of a package."""
    sources = get_pool_sources(distro, package)
    if version is None:
        version_sort(sources)
        return sources.pop()

    for source in sources:
        if version == source["Version"]:
            return source
    else:
        raise IndexError


def get_nearest_source(package, base):
    """Return the base source or nearest to it."""
    try:
        sources = get_pool_sources(SRC_DISTRO, package)
    except IOError:
        sources = []

    bases = []
    for source in sources:
        if base == source["Version"]:
            return source
        elif base > source["Version"]:
            bases.append(source)
    else:
        try:
            return get_pool_source(OUR_DISTRO, package, base)
        except (IOError, IndexError):
            version_sort(bases)
            return bases.pop()


def get_same_source(distro, dist, package):
    """Find the same source in another distribution."""
    for component in DISTROS[distro]["components"]:
        try:
            source = get_source(distro, dist, component, package)
            version = Version(source["Version"])
            pool_source = get_pool_source(distro, package, version)

            return (source, version, pool_source)
        except IndexError:
            pass
    else:
        raise IndexError("%s not found in %s %s" % (package, distro, dist))


# --------------------------------------------------------------------------- #
# Source meta-data handling
# --------------------------------------------------------------------------- #


def get_base(source, slip=False):
    """Get the base version from the given source."""

    def strip_suffix(text, suffix):
        try:
            idx = text.rindex(suffix)
        except ValueError:
            return text

        for char in text[idx + len(suffix) :]:
            if not (char.isdigit() or char == "."):
                return text

        return text[:idx]

    version = source["Version"]
    version = strip_suffix(version, "build")
    version = strip_suffix(version, "ubuntu")

    if version.endswith("-"):
        version += "0"

    if slip and version.endswith("-0"):
        version = version[:-2] + "-1"

    return Version(version)


def version_sort(sources):
    """Sort the source list by version number."""
    sources.sort(key=lambda x: Version(x["Version"]))


def files(source):
    """Return (size, name) for each file."""
    for name in (
        "Checksums-Sha512",
        "Checksums-Sha256",
        "Checksums-Sha1",
        "Files",
    ):
        if name in source:
            files = source[name].strip("\n").split("\n")
            break
    else:
        raise KeyError("Package '%s' has no file list" % source["Package"])
    return [f.split(None, 2)[1:] for f in files]


def read_basis(filename):
    """Read the basis version of a patch from a file."""
    basis_file = filename + "-basis"
    if not os.path.isfile(basis_file):
        return None

    with open(basis_file) as basis:
        return Version(basis.read().strip())


def save_basis(filename, version):
    """Save the basis version of a patch to a file."""
    basis_file = filename + "-basis"
    with open(basis_file, "w") as basis:
        print("%s" % version, file=basis)


# --------------------------------------------------------------------------- #
# Unpacked source handling
# --------------------------------------------------------------------------- #


def unpack_source(distro, source):
    """Unpack the given source and return location."""
    destdir = unpack_directory(source)
    if os.path.isdir(destdir):
        return destdir

    srcdir = "%s/%s" % (ROOT, source["Directory"])
    for _, name in files(source):
        if name.endswith(".dsc"):
            dsc_file = name
            break
    else:
        raise ValueError("Missing dsc file")

    ensure(destdir)
    try:
        env = dict(os.environ)
        env["DEB_VENDOR"] = distro
        with open(os.devnull, "wb") as devnull:
            subprocess.check_call(
                ("dpkg-source", "--skip-patches", "-x", dsc_file, destdir),
                cwd=srcdir,
                env=env,
                stdout=devnull,
                stderr=devnull,
            )
        # Make sure we can at least read everything under .pc, which isn't
        # automatically true with dpkg-dev 1.15.4.
        pc_dir = os.path.join(destdir, ".pc")
        for filename in tree.walk(pc_dir):
            pc_filename = os.path.join(pc_dir, filename)
            pc_stat = os.lstat(pc_filename)
            if pc_stat is not None and stat.S_IMODE(pc_stat.st_mode) == 0:
                os.chmod(pc_filename, 0o400)
    except Exception:
        cleanup(destdir)
        raise

    return destdir


def cleanup_source(source):
    """Cleanup the given source's unpack location."""
    cleanup(unpack_directory(source))


def save_changes_file(filename, source, previous=None):
    """Save a changes file for the given source."""
    srcdir = unpack_directory(source)

    filesdir = "%s/%s" % (ROOT, source["Directory"])

    ensure(filename)
    with open(filename, "w") as changes:
        cmd = ("dpkg-genchanges", "-S", "-u%s" % filesdir)
        orig_cmd = cmd
        if previous is not None:
            cmd += ("-v%s" % previous["Version"],)

        with open(os.devnull, "wb") as devnull:
            try:
                subprocess.check_call(
                    cmd, cwd=srcdir, stdout=changes, stderr=devnull
                )
            except subprocess.CalledProcessError:
                subprocess.check_call(
                    orig_cmd, cwd=srcdir, stdout=changes, stderr=devnull
                )

    return filename


def save_patch_file(filename, last, this):
    """Save a diff or patch file for the difference between two versions."""
    lastdir = unpack_directory(last)
    thisdir = unpack_directory(this)

    diffdir = os.path.commonprefix((lastdir, thisdir))
    diffdir = diffdir[: diffdir.rindex("/")]

    lastdir = tree.subdir(diffdir, lastdir)
    thisdir = tree.subdir(diffdir, thisdir)

    ensure(filename)
    with open(filename, "w") as diff:
        diff_args = ("diff", "-pruN", lastdir, thisdir)
        with open(os.devnull, "wb") as devnull:
            status = subprocess.call(
                diff_args, cwd=diffdir, stdout=diff, stderr=devnull
            )
        if status not in {0, 1, 2}:
            raise subprocess.CalledProcessError(status, diff_args)


# --------------------------------------------------------------------------- #
# Merge data handling
# --------------------------------------------------------------------------- #


def read_report(output_dir, left_distro, right_distro):
    """Read the report to determine the versions that went into it."""
    filename = "%s/REPORT" % output_dir
    if not os.path.isfile(filename):
        raise ValueError("No report exists")

    base_version = None
    left_version = None
    right_version = None

    with open(filename) as report:
        for line in report:
            if line.startswith("base:"):
                base_version = Version(line[5:].strip())
            elif line.startswith("%s:" % left_distro):
                left_version = Version(line[len(left_distro) + 1 :].strip())
            elif line.startswith("%s:" % right_distro):
                right_version = Version(line[len(right_distro) + 1 :].strip())

    if base_version is None or left_version is None or right_version is None:
        raise AttributeError("Insufficient detail in report")

    return (base_version, left_version, right_version)


# --------------------------------------------------------------------------- #
# Blacklist handling
# --------------------------------------------------------------------------- #


def read_blocklist():
    """Read the blocklist file."""
    filename = "%s/sync-blocklist.txt" % ROOT
    if not os.path.isfile(filename):
        return []

    bl = []
    with open(filename) as blocklist:
        for line in blocklist:
            try:
                line = line[: line.index("#")]
            except ValueError:
                pass

            line = line.strip()
            if not line:
                continue

            bl.append(line)

    return bl


# --------------------------------------------------------------------------- #
# RSS feed handling
# --------------------------------------------------------------------------- #


def read_rss(filename, title, link, description):
    """Read an RSS feed, or generate a new one."""
    rss = ElementTree.Element("rss", version="2.0")

    channel = ElementTree.SubElement(rss, "channel")

    e = ElementTree.SubElement(channel, "title")
    e.text = title

    e = ElementTree.SubElement(channel, "link")
    e.text = link

    e = ElementTree.SubElement(channel, "description")
    e.text = description

    now = time.gmtime()

    e = ElementTree.SubElement(channel, "pubDate")
    e.text = time.strftime(RSS_TIME_FORMAT, now)

    e = ElementTree.SubElement(channel, "lastBuildDate")
    e.text = time.strftime(RSS_TIME_FORMAT, now)

    e = ElementTree.SubElement(channel, "generator")
    e.text = "Merge-o-Matic"

    if os.path.isfile(filename):
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=7)

        tree = ElementTree.parse(filename)
        for i, item in enumerate(tree.find("channel").findall("item")):
            dt = datetime.datetime(
                *time.strptime(item.findtext("pubDate"), RSS_TIME_FORMAT)[:6]
            )
            if dt > cutoff or i < 10:
                channel.append(item)

    return rss


def write_rss(filename, rss):
    """Write out an RSS feed."""
    ensure(filename)
    etree = ElementTree.ElementTree(rss)
    with tree.AtomicFile(filename) as fd:
        etree.write(fd)


def append_rss(rss, title, link, author=None, filename=None):
    """Append an element to an RSS feed."""
    item = ElementTree.Element("item")

    e = ElementTree.SubElement(item, "title")
    e.text = title

    e = ElementTree.SubElement(item, "link")
    e.text = link

    if author is not None:
        e = ElementTree.SubElement(item, "author")
        e.text = author

    if filename is not None:
        e = ElementTree.SubElement(item, "pubDate")
        e.text = time.strftime(
            RSS_TIME_FORMAT, time.gmtime(os.stat(filename).st_mtime)
        )

    channel = rss.find("channel")
    for i, e in enumerate(channel):
        if e.tag == "item":
            channel.insert(i, item)
            break
    else:
        channel.append(item)


# --------------------------------------------------------------------------- #
# Comments handling
# --------------------------------------------------------------------------- #


def comments_file():
    """Return the location of the comments."""
    return "%s/comments.txt" % ROOT


def get_comments():
    """Extract the comments from file, and return a dictionary
       containing comments corresponding to packages"""
    comments = {}

    with open(comments_file(), "r") as file_comments:
        fcntl.flock(file_comments, fcntl.LOCK_SH)
        for line in file_comments:
            if ": " not in line:
                continue
            package, comment = line.rstrip("\n").split(": ", 1)
            comments[package] = comment

    return comments


def add_comment(package, comment):
    """Add a comment to the comments file"""
    with open(comments_file(), "a") as file_comments:
        fcntl.flock(file_comments, fcntl.LOCK_EX)
        the_comment = comment.replace("\n", " ")
        the_comment = escape(the_comment[:100], quote=True)
        file_comments.write("%s: %s\n" % (package, the_comment))


def remove_old_comments(status_file, merges):
    """Remove old comments from the comments file using
       component's existing status file and merges"""
    if not os.path.exists(status_file):
        return

    packages = [m[2] for m in merges]
    toremove = []

    with open(status_file, "r") as file_status:
        for line in file_status:
            package = line.split(" ")[0]
            if package not in packages:
                toremove.append(package)

    with open(comments_file(), "a+") as file_comments:
        fcntl.flock(file_comments, fcntl.LOCK_EX)

        new_lines = []
        for line in file_comments:
            if line.split(": ", 1)[0] not in toremove:
                new_lines.append(line)

        file_comments.truncate(0)

        for line in new_lines:
            file_comments.write(line)


def gen_buglink_from_comment(comment):
    """Return an HTML formatted Debian/Ubuntu bug link from comment"""
    debian = re.search(".*Debian bug #([0-9]{1,}).*", comment, re.I)
    ubuntu = re.search(".*bug #([0-9]{1,}).*", comment, re.I)

    html = ""
    if debian:
        html += '<img src=".img/debian.png" alt="Debian" />'
        html += '<a href="https://bugs.debian.org/%s">#%s</a>' % (
            debian.group(1),
            debian.group(1),
        )
    elif ubuntu:
        html += '<img src=".img/ubuntu.png" alt="Ubuntu" />'
        html += '<a href="https://launchpad.net/bugs/%s">#%s</a>' % (
            ubuntu.group(1),
            ubuntu.group(1),
        )
    else:
        html += "&nbsp;"

    return html


# --------------------------------------------------------------------------- #
# Launchpadlib functions
# --------------------------------------------------------------------------- #

LAUNCHPAD = None


def get_launchpad():
    global LAUNCHPAD

    if LAUNCHPAD is None:
        LAUNCHPAD = Launchpad.login_anonymously("merge-o-matic", "production")
    return LAUNCHPAD


def get_date_superseded(package, base_version):
    from debian.debian_support import Version

    base_version = Version(base_version)

    src_distro = get_launchpad().distributions[SRC_DISTRO]
    src_series_name = SRC_DIST
    # Hack to cope with Launchpad only knowing about Debian codenames, not
    # suite names.
    if src_series_name == "unstable":
        src_series_name = "sid"
    src_series = src_distro.getSeries(name_or_version=src_series_name)
    src_archive = src_distro.main_archive

    date_superseded = None
    for spph in src_archive.getPublishedSources(
        source_name=package,
        distro_series=src_series,
        exact_match=True,
        pocket="Release",
    ):
        version = Version(spph.source_package_version)
        if version <= base_version:
            break
        date_superseded = spph.date_created
    else:
        if False:
            print(
                "Base version %s of %s never published in Debian %s."
                % (base_version, package, SRC_DIST)
            )
    return date_superseded


def proposed_package_version(package, our_version):
    from debian.debian_support import Version

    our_version = Version(our_version)

    our_distro = get_launchpad().distributions[OUR_DISTRO]
    our_series = our_distro.getSeries(name_or_version=OUR_DIST)
    our_archive = our_distro.main_archive

    proposed_pkg = None
    for spph in our_archive.getPublishedSources(
        source_name=package,
        distro_series=our_series,
        exact_match=True,
        pocket="Proposed",
    ):
        if spph.status not in ["Pending", "Published"]:
            continue
        version = Version(spph.source_package_version)
        if version >= our_version:
            proposed_pkg = spph.source_package_version
            break
        if version < our_version:
            break
    return proposed_pkg


def download_source(distro, source, targetdir):
    for size, name in files(source):
        # We compose the URL manually rather than going through launchpadlib
        # to save several round-trips.
        url = (
            "https://launchpad.net/%s/+archive/primary/"
            "+sourcefiles/%s/%s/%s"
            % (
                quote(distro),
                quote(source["Package"]),
                quote(source["Version"]),
                quote(name),
            )
        )
        filename = os.path.join(targetdir, name)

        logging.debug("Downloading %s", url)
        ensure(filename)
        try:
            with closing(urlopen(url)) as url_f, open(filename, "wb") as out_f:
                for chunk in iter(lambda: url_f.read(256 * 1024), ""):
                    out_f.write(chunk)
        except IOError:
            logging.warning("Downloading %s failed", url)
            raise
        logging.info("Saved %s", name)
