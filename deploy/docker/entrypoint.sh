#!/bin/sh
# What the Sofa container starts with (Dockerfile ENTRYPOINT).
#
# The first start writes a config.json into Sofa's data folder (SOFA_DATA, /data in the image) that points the
# library at /media, the folder compose.yml maps your media into: /media/Shows, /media/Movies, /media/Inbox and the
# rest. Sofa makes those folders itself. A config.json that's there already is left exactly as it is, so your own
# settings (another port, folders elsewhere, a TMDB key) survive every new image. Drives for Server → Storage are
# looked for under /mnt, where a second volume mapping can put them; /media is the library, not a drive.
#
# Sofa runs as the user PUID:PGID (1000:1000 unless compose.yml is told otherwise), never as root: the container
# starts as root only to hand /data and /media to that user when Docker created them, and drops to it at once.
#
# Then Sofa itself, with whatever arguments the container was given ("serve" by default): `docker compose run
# --rm sofa status`, `... backup`, `... inbox` work the same as `python3 sofa.py ...`.
set -e
DATA="${SOFA_DATA:-/data}"
MEDIA="${SOFA_MEDIA:-/media}"
PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
if [ "$(id -u)" = "0" ]; then
  # Started as root (the image's default): the two folders go to Sofa's user when Docker made them (a first
  # `docker compose up` in an empty folder leaves them root's), the folders only, nothing inside them. Then the rest
  # of this script, and Sofa, run as that user and never as root.
  for d in "$DATA" "$MEDIA"; do
    mkdir -p "$d"
    [ "$(stat -c %u "$d")" = "$PUID" ] || chown "$PUID:$PGID" "$d" || echo "Couldn't make $d belong to $PUID:$PGID; Sofa may not be able to write there."
  done
  exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups --inh-caps=-all "$0" "$@"
fi
if [ ! -f "$DATA/config.json" ]; then
  mkdir -p "$DATA"
  cat > "$DATA/config.json.tmp" <<EOF
{
  "shows": "$MEDIA/Shows",
  "movies": "$MEDIA/Movies",
  "music": "$MEDIA/Music",
  "musicvideos": "$MEDIA/Music Videos",
  "inbox": "$MEDIA/Inbox",
  "review": "$MEDIA/Needs Review",
  "adult": "$MEDIA/Adult",
  "originals": "$MEDIA/Converted Originals",
  "drive_folders": ["/mnt"]
}
EOF
  mv "$DATA/config.json.tmp" "$DATA/config.json"
  echo "First start: the library is under $MEDIA (settings in $DATA/config.json)."
fi
[ $# -eq 0 ] && set -- serve
exec python3 "$(dirname "$0")/../../sofa.py" "$@"
