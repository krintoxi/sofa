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
#
# The graphics chip (docs/install.md, "The graphics chip in Docker"). Debian's ffmpeg has VA-API's and NVIDIA's
# encoders built in; what a container needs besides is the driver that talks to the chip:
#   - amd64: VA-API's drivers for Intel's graphics (intel-media-va-driver) and AMD's (mesa-va-drivers), and Intel's
#     Quick Sync runtime where Debian has it. They do nothing until a render node is passed in (`--device /dev/dri`).
#   - NVIDIA: nothing here. NVIDIA's container toolkit brings its own libraries in (`--gpus all`); the
#     NVIDIA_DRIVER_CAPABILITIES below asks it for the video ones.
#
# Debian's ffmpeg also brings Mesa's software OpenGL along (for the preview window ffplay-style tools can open: 180 MB
# of LLVM and drivers) that a server never draws with. On arm64, where no PC graphics chip is, those packages are
# removed again, with dpkg told to ignore the dependency; ffmpeg loads and converts without them (the image's tests
# play an HEVC MKV through it). `apt-get` inside that image would want them back; nothing else notices. On amd64
# they stay: AMD's VA-API driver is part of Mesa.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg procps \
 && arch="$(dpkg --print-architecture)" \
 && if [ "$arch" = "amd64" ]; then \
      apt-get install -y --no-install-recommends intel-media-va-driver mesa-va-drivers \
      && { apt-get install -y --no-install-recommends libmfx-gen1.2 || echo "No Quick Sync runtime in this archive: VA-API covers Intel's graphics."; }; \
    fi \
 && rm -rf /var/lib/apt/lists/* \
 && if [ "$arch" != "amd64" ]; then \
      gl="$(dpkg-query -W -f '${db:Status-Status} ${Package}\n' 'libgl1-mesa-dri' 'mesa-libgallium' 'libllvm*' 'libz3-*' 2>/dev/null | awk '$1 == "installed" {print $2}' | tr '\n' ' ')" \
      && dpkg --purge --force-depends $gl; \
    fi \
 && ffmpeg -v error -f lavfi -i testsrc2=size=320x180:rate=25 -t 1 -c:v libx264 -f null - \
 && ffmpeg -hide_banner -encoders | grep -E ' h264_(vaapi|nvenc|qsv) ' \
 && ffmpeg -hide_banner -encoders | grep -q ' h264_vaapi ' \
 && ffmpeg -hide_banner -encoders | grep -q ' h264_nvenc ' \
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
# when Docker made them (a first `docker compose up` in an empty folder), then drops to it with setpriv, in the
# groups that own the render nodes the container was given (/dev/dri), so the graphics chip is open to Sofa.
# NVIDIA_DRIVER_CAPABILITIES: what NVIDIA's container toolkit brings in when the container is given a GPU; "video" is
# the encoder. It means nothing without that toolkit.
ARG SOFA_COMMIT=""
ENV SOFA_DATA=/data \
    SOFA_CONTAINER=ghcr.io/krintoxi/sofa \
    NVIDIA_DRIVER_CAPABILITIES=compute,video,utility \
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
