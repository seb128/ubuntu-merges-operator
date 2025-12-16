#!/bin/sh
# grab-merge.sh - grab a merge
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

# Uncomment if you know that this deletes all the files in the CWD
#EXPERT=y

# Or uncommit if you want to use named subdirectories
#SUBDIR=y


set -e

MERGE=$1

if [ "$SUBDIR" = "y" ]; then
    [ -d "$MERGE" ] || mkdir "$MERGE"
    cd "$MERGE"
fi

if [ "$EXPERT" != "y" ] && [ -n "$(ls)" ]; then
    echo -n "Sure you want to delete all the files in $(pwd) [yn]? "
    read ANSWER
    [ "$ANSWER" = y ]
fi

if [ "${MERGE#lib}" != "${MERGE}" ]; then
    HASH=${MERGE%${MERGE#????}}
else
    HASH=${MERGE%${MERGE#?}}
fi

rm -rf  *
wget -q "https://merges.ubuntu.com/$HASH/$MERGE/REPORT"

for NAME in $(sed -n -e "/^    /p" REPORT); do
    echo "Getting $NAME..."
    [ -f "$NAME" ] || wget -q "https://merges.ubuntu.com/$HASH/$MERGE/$NAME"
done
echo

if grep "^generated: " REPORT >/dev/null; then
    VERSION=$(sed -n -e "/^generated:/s/^generated: *//p" REPORT)
    dpkg-source -x "${MERGE}_${VERSION#*:}.dsc"
    echo
else
    TARBALL=$(sed -n -e "/\.src\.tar\.gz$/p" REPORT)

    echo "unpacking $TARBALL"
    tar xf "$TARBALL"
    echo
fi

if grep "^  C" REPORT; then
    echo
fi

echo "#!/bin/sh" > merge-genchanges
echo "exec $(sed -n -e '/^  $ /s/^  $ //p' REPORT) \"\$@\"" \
    >> merge-genchanges
chmod +x merge-genchanges

echo "#!/bin/sh" > merge-buildpackage
echo "exec $(sed -n -e '/^  $ /s/^  $ dpkg-genchanges/dpkg-buildpackage/p' REPORT) \"\$@\"" \
    >> merge-buildpackage
chmod +x merge-buildpackage

echo "Run ../merge-genchanges or ../merge-buildpackage when done"

if grep "^Vcs-" *.dsc >/dev/null; then
    echo
    echo "*** WARNING ***"
    echo
    echo "It looks like this package is maintained in revision control:"
    echo
    grep "^Vcs-" *.dsc
    echo
    echo "You almost certainly don't want to continue without investigating."
    exit 1
fi
