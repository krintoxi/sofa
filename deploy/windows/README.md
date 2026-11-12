# Sofa for Windows

Sofa's server as a Windows app: an installer that brings its own Python and ffmpeg, an icon by the clock that shows
Sofa running and opens it, start with Windows, an uninstaller, and a firewall question that says what it's for. One
code base: the same `sofa/` runs on a Mac, on Linux, in Docker and on Windows; what only Windows needs is in
`sofa/windows.py` (Windows' own APIs, through ctypes) and `sofa/winapp.py` (the app).

How to install and use it: [docs/install.md, "On Windows"](../../docs/install.md#on-windows).

## What's here

| | |
|---|---|
| `sofa.iss` | the installer (Inno Setup 6) |
| `sofa-tray.pyw` | what the Start menu and "start with Windows" run: the app in the notification area (`sofa/winapp.py`) |
| `sofa.ico`, `sofa-stopped.ico` | the app's icons: Sofa's own colours while it runs, grey while it starts or is stopped. Made from `client/icons/icon-512.png` at 16 to 256 pixels (PNG inside the .ico); the grey one through macOS's Generic Gray colour profile |

Elsewhere: `tools/windows-deps.py` (the Python and ffmpeg it carries, at fixed versions, checked byte for byte),
`tools/windows-build.py` (puts it together in `build/windows/Sofa`), `.github/workflows/windows.yml` (builds,
tests and releases it), `tests/test_windows.py`.

## How it's built

GitHub builds it on `windows-latest` from every change to Sofa (`.github/workflows/windows.yml`):

1. `python tools/windows-build.py`: Sofa's code (exactly what an update replaces: `CODE` in `sofa/updater.py`) into
   `build/windows/Sofa`, Python 3.14.10 (python.org's embeddable build) into `vendor\python` and ffmpeg 9.0.2 (Gyan
   Doshi's full build with shared libraries, the one ffmpeg.org points to for Windows: x264, chromaprint for Skip
   Intro, the GPU encoders) into `vendor\ffmpeg`, without `ffplay`.
2. Sofa's whole test suite with that Python.
3. `iscc /DAppVersion=<version> deploy\windows\sofa.iss` → `build\windows\sofa-<version>-windows-x64-setup.exe`
   (88 MB; 274 MB once installed, 230 of them ffmpeg).
4. The installer is run there: installed with no questions, Sofa started as the Start menu starts it, its page
   asked for, its library where it was told, Quit, uninstalled, and what each step left looked at.
5. On `main`: a release `sofa-v<version>` with the installer and its SHA-256, and the release `sofa-for-windows`
   with the newest as `sofa-windows-x64-setup.exe`.

On a Windows PC of your own (Python 3.9 or newer, Inno Setup 6): `python tools\windows-build.py`, then
`"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DAppVersion=1.5.9 deploy\windows\sofa.iss`.

To move to a newer Python or ffmpeg: the version, address and SHA-256 in `tools/windows-deps.py`, together.

## What it puts where

| | |
|---|---|
| `%LOCALAPPDATA%\Programs\Sofa` | Sofa, for the person who installed it (no administrator needed: Sofa updates its own code in place, so the folder has to be theirs) |
| `...\Sofa\vendor\python`, `...\vendor\ffmpeg` | the Python and ffmpeg it runs with, its own, nothing shared with the rest of the PC |
| `...\Sofa\data` | accounts, watch history, settings, artwork, backups, `sofa.log`: made on the PC, never shipped |
| the library | where the installer's "Your library" page said (`%USERPROFILE%\Entertainment` unless changed): Shows, Movies, Music, Music Videos, Inbox |
| Start menu | **Sofa** (and on the desktop when ticked) |
| `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, `Sofa` | start with Windows (ticked by default; the app's menu turns it on and off) |
| Windows Firewall | one inbound rule, **Sofa**: Sofa's own `python.exe` on private networks, when allowed (an administrator's yes) |
| `HKLM\SYSTEM\CurrentControlSet\Control\FileSystem`, `LongPathsEnabled` | only when "longer than 260 characters" is ticked (an administrator's yes) |

## How Sofa runs on Windows

- The app (`pythonw.exe deploy\windows\sofa-tray.pyw`) runs `python.exe -X utf8 sofa.py serve` with no window and its
  output added to `data\sofa.log`, inside a Windows job object: when the app ends, however it ends, Windows ends the
  server and every ffmpeg it started. The server has a console nobody sees, which its ffmpegs share, so no window
  flashes up when one starts.
- It's started again when it stops (after 15 seconds, like launchd's ThrottleInterval on a Mac), at once when it
  asks to be (after an update: exit code 75, since a Windows process can't replace itself the way `os.execv` does),
  and after five stops in two minutes it's left stopped, with a notification and **Open the log** in the menu.
- **Quit**, signing out, shutting down and the installer ask the server to stop through a named event it watches
  (`SOFA_STOP_EVENT`): it takes back its Bonjour and SSDP announcements first, the way SIGTERM is used elsewhere.
- One app per Sofa folder: opening Sofa from the Start menu again opens the browser instead.
- Windows' own versions of what Sofa uses elsewhere: Bonjour through Windows' DNS-SD service (no Apple Bonjour
  needed; Windows 10 1809 and newer), staying awake with `SetThreadExecutionState` (not `caffeinate`), drive letters
  for Server → Storage (not `/Volumes`), the CPU and memory from Windows itself, below-normal priority for background
  conversions (not `nice`), and Sofa's port taken exclusively (on Windows, `SO_REUSEADDR` would let a second Sofa
  share it).
- Python runs in UTF-8 mode, so names and text are UTF-8 as on a Mac or Linux, not the PC's old code page.

## Updates

**Server → Updates → Update now** replaces Sofa's code in place, as on a Mac (`sofa/updater.py`, `sofa/swap.py`);
the app starts the new version. The Python and ffmpeg in `vendor\` change only with a newer installer, which installs
over the old one and keeps `data\` and the library.

## Signing (a step for the owner)

There's no code-signing certificate yet, so Windows SmartScreen says it doesn't recognise the installer ("Windows
protected your PC": **More info**, then **Run anyway**). Python's own `python.exe` and `pythonw.exe` inside are signed
by the Python Software Foundation; the installer, its uninstaller and ffmpeg's files aren't.

To sign:

1. Get a code-signing certificate: an OV certificate from a certificate authority (the name on it is checked; about
   $200-400 a year, delivered on a hardware token or in a cloud HSM), or Microsoft's Azure Trusted Signing (a monthly
   fee; the identity check takes days). An OV certificate still builds SmartScreen reputation over the first
   downloads; there's no instant pass any more.
2. Sign with the Windows SDK's `signtool`. Inno Setup signs the installer and the uninstaller itself:

   ```
   iscc /DSign /DAppVersion=1.5.9 "/Ssofa=signtool.exe sign /fd sha256 /tr http://timestamp.digicert.com /td sha256 /f sofa.pfx /p PASSWORD $f" deploy\windows\sofa.iss
   ```

   (with a token or a cloud HSM, its own `signtool` arguments instead of `/f` and `/p`).
3. In `.github/workflows/windows.yml`: the certificate as repository secrets (or the signing service's
   credentials), and the `iscc` line above in the "Build the installer" step. ffmpeg's files can be signed the same
   way before step 3, in `build\windows\Sofa\vendor\ffmpeg\bin`.

## What has been tested, and how

On GitHub's Windows machines (Windows Server, `windows-latest`), on every change:

- Sofa's whole test suite with Python 3.9 and 3.12 (`.github/workflows/tests.yml`) and with the Python 3.14 the
  installer carries, real ffmpeg 9.0.2 included; the box's tests are skipped there, with the reason
  (`WINDOWS_SKIPS` in `tests/__init__.py`): Sofa Box OS is Linux.
- `tests/test_windows.py`: the server in its job object stopped cleanly and its child processes gone with it; the
  app started, asked for its status, started a second time (the first stays), quit; Windows' own Bonjour, staying
  awake, drive letters, the port Sofa's alone; start with Windows (and Task Manager switching it off).
- The installer, end to end (above, "How it's built", step 4), including the firewall rule made and removed.

**Not yet on a real Windows PC.** Nobody has run the installer on a PC at home: the wizard's pages as a person sees
them, the icon by the clock and its menu, the browser opening, start with Windows after a real sign-in, the firewall
question on a real home network, a TV or phone finding Sofa by SSDP or Bonjour, playback to a real device, an update
through Server → Updates, Windows 10, Windows on ARM (it runs as x64 there, emulated), and antivirus programs other than
Microsoft Defender. GitHub's machines are Windows Server with no one signed in at a screen and no home network.

## Known limits

- 64-bit Windows 10 (1809) or 11 only; no ARM64 build.
- Task Manager lists Sofa as Python (it is Python: `pythonw.exe` for the app, `python.exe` for the server).
- Sofa runs while you're signed in (start with Windows), like Plex's Windows app; not as a Windows service.
- Video is converted with x264, as on Linux; the GPU encoders in this ffmpeg (NVIDIA, Intel, AMD) aren't used yet.
- A USB drive "as it is" (sorted with links, `auto_drives`, what a Sofa Box does) needs Windows' Developer Mode for
  symbolic links. The usual way, a library folder on the drive (Server → Storage), doesn't.
- Mapped network drives aren't listed under Storage; a folder on one can still be added by its path.
