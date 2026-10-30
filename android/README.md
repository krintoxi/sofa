# Sofa for Fire TV

Sofa's own TV pages, with videos played by Android's player: MKV, HEVC and Dolby sound play as
they are, so the Sofa computer hardly ever has to convert anything (and an old Mac stays cool).

## Installing it on a Fire TV

**The easy way:** open Sofa in **Silk** on the Fire TV. Home shows **Install the Sofa app**: press it
and follow the two steps on screen (turn on **ADB debugging** on the Fire TV, then answer the TV's
"Allow?" question once). The Sofa computer puts the app on the Fire TV over your home network and
opens it. Later, when Sofa has a newer app, the app itself shows **Update the app**.

The Sofa computer keeps the app (`data/apps/sofa-firetv.apk`): it gets the newest one from this
repository's Releases a minute after starting and then once a day, unless Sofa is set to work offline.
Installing on a Fire TV never needs the internet.

**The other way, with Downloader:**

1. On the Fire TV: **Settings → My Fire TV → Developer options → Install unknown apps**, and allow
   it for **Downloader** (install Downloader from the Amazon Appstore first; it's free).
   (No Developer options? **Settings → My Fire TV → About**, press OK on the device name 7 times.)
2. Open Downloader and type the Sofa address with `/firetv` on the end, for example
   `http://192.168.1.20:8090/firetv` (the Server page shows yours under **Apps**). Install.
3. Open **Sofa** from the Fire TV's apps. It finds the Sofa computer by itself (or type its
   address), then shows a code: approve it on your phone (Sofa → Pair a TV, or scan the QR).

Updating: the same steps install a newer version over the old one, keeping the sign-in.

## How it's built

GitHub builds it (`.github/workflows/android.yml`) whenever this folder changes, and publishes
`sofa-firetv.apk` on the repository's Releases page from `main` as `firetv-<build>`. Sofa fetches the
newest of those (`sofa/apps.py`, checked against GitHub's SHA-256), serves it at `/firetv`, and installs
it over the network with a small ADB client of its own (`sofa/adb.py`, standard library only; its key
is in `data/adb/`, and a Fire TV only accepts it after you press OK on the TV).

To build it yourself: Android Studio, or `gradle assembleRelease` in this folder with the Android SDK.

**The signing key** (`sofa-sideload.jks`, password `sofa-sideload`) is in this folder on purpose: every
build is signed with the same key, so updates install over the old version. It only proves "built
from this repository", so install Sofa only from your own Sofa computer or this repository's
Releases page.
