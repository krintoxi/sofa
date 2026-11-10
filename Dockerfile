# Sofa in a container: Python's standard library and Debian's ffmpeg, nothing else.
#
#     docker compose up -d                      (compose.yml: host networking, ./data and ./media)
#
# or by hand, from this folder:
#
#     docker build -t sofa .
#     docker run -d --name sofa --init --network host -v ./data:/data -v ./media:/media sofa
#
# Then open http://<this computer>:8090 from a device at home and create the admin account. The image is
# published as ghcr.io/krintoxi/sofa (.github/workflows/docker-image.yml); what's in it: docs/install.md, "In Docker".
#
# Two folders of yours: /data (accounts, watch history, settings, artwork, backups: Sofa's data/ folder) and /media
# (Shows/, Movies/, Music/, Music Videos/, Inbox/, Needs Review/, Adult/, Converted Originals/). On the first start,
# deploy/docker/entrypoint.sh writes a config.json that points the library at /media unless /data has one already.
FROM python:3.12-slim-trixie

ARG DEBIAN_FRONTEND=noninteractive
# ffmpeg: Debian's own build (with chromaprint for Skip Intro). procps: `ps`, which Sofa uses to find a helper it
# started before a restart. Nothing else; no Python packages at all.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg procps \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd -g 1000 sofa \
 && useradd -u 1000 -g sofa -d /data -M -s /usr/sbin/nologin sofa \
 && mkdir -p /data /media \
 && chown sofa:sofa /data /media

WORKDIR /opt/sofa
COPY . /opt/sofa
RUN python3 -m compileall -q /opt/sofa/sofa /opt/sofa/sofa.py \
 && chmod 0755 /opt/sofa/deploy/docker/entrypoint.sh

# The commit this image was built from (the workflow passes it), so Server → Updates can say which one runs and
# whether GitHub has a newer one. SOFA_CONTAINER tells Sofa it runs from an image: "Update now" then says to pull a
# new one instead of swapping files in place (sofa/updater.py). PUID and PGID: the user Sofa runs as (the one that
# should own /data and /media on the computer); the entrypoint starts as root only to hand those two folders to it
# when Docker made them (a first `docker compose up` in an empty folder), then drops to it with setpriv.
ARG SOFA_COMMIT=""
ENV SOFA_DATA=/data \
    SOFA_CONTAINER=ghcr.io/krintoxi/sofa \
    SOFA_COMMIT=$SOFA_COMMIT \
    PUID=1000 \
    PGID=1000 \
    HOME=/data \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

LABEL org.opencontainers.image.title="Sofa" \
      org.opencontainers.image.description="A small, self-hosted home media server: your own streaming service, at home." \
      org.opencontainers.image.source="https://github.com/krintoxi/sofa" \
      org.opencontainers.image.licenses="PolyForm-Noncommercial-1.0.0"

VOLUME ["/data", "/media"]
# Sofa's port is the `port` setting in /data/config.json (8090 unless changed); with host networking it's the
# computer's own port, so nothing to publish here.
EXPOSE 8090
# /api/info answers without a sign-in, on the port the settings name.
HEALTHCHECK --interval=60s --timeout=10s --start-period=40s --retries=3 \
  CMD python3 -c "import json, urllib.request; p = json.load(open('/data/config.json')).get('port', 8090); urllib.request.urlopen('http://127.0.0.1:%d/api/info' % p, timeout=8)" || exit 1

ENTRYPOINT ["/opt/sofa/deploy/docker/entrypoint.sh"]
CMD ["serve"]
