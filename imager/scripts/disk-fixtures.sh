#!/bin/sh
# Makes the test disks that need macOS's own tools (hdiutil makehybrid's UDF and ISO 9660 images, newfs_msdos's
# efisys.bin) and commits them as skeletons under Tests/ImagerKitTests/Fixtures/disks, with disks.json saying where
# each file's contents go back (see DiskFixture in Tests/ImagerKitTests/DiskFixtures.swift). Every system's tests
# then read exactly what macOS made. Run it on a Mac with xz on the PATH, after changing how a test disk is made:
#
#     imager/scripts/disk-fixtures.sh
set -e
cd "$(dirname "$0")/.."
[ "$(uname)" = Darwin ] || { echo "needs macOS (hdiutil, newfs_msdos)" >&2; exit 1; }
command -v xz >/dev/null || { echo "needs xz on the PATH" >&2; exit 1; }
out="$PWD/Tests/ImagerKitTests/Fixtures/disks"
mkdir -p "$out"
SOFA_IMAGER_MAKE_DISK_FIXTURES="$out" swift test --filter DiskFixtureTests/testMakeTheDiskFixtures 2>&1 \
  | grep -E "disk fixture|error:|Executed 1 test"
ls -l "$out"
