# Sofa for Fire TV

Sofa's own TV pages, with videos played by Android's player: MKV, HEVC and Dolby sound play as
they are, so the Sofa computer hardly ever has to convert anything (and an old Mac stays cool).

## Installing it on a Fire TV

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
`sofa-firetv.apk` on the repository's Releases page from `main`. Sofa's `/firetv` address serves
`~/Sofa/data/apps/sofa-firetv.apk` if you put one there (no internet needed), or sends the Fire TV
to the latest release.

To build it yourself: Android Studio, or `gradle assembleRelease` in this folder with the Android SDK.

**The signing key** (`sofa-sideload.jks`, password `sofa-sideload`) is in this folder on purpose: every
build is signed with the same key, so updates install over the old version. It only proves "built
from this repository", so install Sofa only from your own Sofa computer or this repository's
Releases page.
