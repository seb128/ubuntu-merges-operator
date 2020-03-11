#!/bin/sh

set -e
umask 002

MOMLIB_ROOT=/srv/patches.ubuntu.com

cd $MOMLIB_ROOT

find changes -name "*.changes" -mtime +182 -print0 | xargs -0r bzip2 -q
find diffs -name "*.patch" -mtime +182 -print0 | xargs -0r bzip2 -q
find patches \( -name "*.patch" -o -name "*.slipped-patch" \) -mtime +182 -print0 | xargs -0r bzip2 -q
