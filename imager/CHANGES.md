# Sofa Box Imager: what's new

The Mac app in this folder. Each build on `main` replaces the zip on the
[`sofa-box-imager` release](https://github.com/krintoxi/sofa/releases/tag/sofa-box-imager). Its version is `VERSION`
here. Until 0.3.0 its changes were written up with Sofa Box OS's, in `deploy/sofa-box/CHANGES.md`.

## 0.4.0

**A universal imager: other Linux systems, Windows installers and your own images, as well as Sofa Box OS.** The
switch at the top of the window has four choices now: Sofa Box OS (as before: For a Raspberry Pi, For a PC, On a DVD),
**Linux**, **Windows** and **Your own image**. Whatever is written goes through the same writer as a Sofa Box card:
the same disk rule, the first megabyte held back and written last, every byte read back and checked, then ejected.

- **Linux.** A short list we keep: Ubuntu Desktop (the newest LTS), Debian (the stable installer), Fedora Workstation,
  Linux Mint Cinnamon, and Raspberry Pi OS with and without its desktop. Nothing in the list names a version: each
  entry finds its project's newest release on the project's own site when it's chosen, and the file is checked against
  that project's own SHA-256 list, fetched fresh over HTTPS (Ubuntu's and Debian's SHA256SUMS, Mint's sha256sum.txt,
  Fedora's releases.json, Raspberry Pi's own list). An ISO is written to the stick whole, as its project publishes it;
  Raspberry Pi OS is unpacked as it's written, to an SD card.
- **Windows 7, 8.1, 10 and 11**, from an ISO you bring. Sofa Box Imager never downloads Windows; for 10 and 11 it links
  to Microsoft's own download pages. It reads the ISO itself (its UDF file system, and the Windows image's own list of
  editions) and makes a FAT32 stick that starts PCs with UEFI, Secure Boot on or off, and older ones with BIOS:
  - `install.wim` over FAT32's 4 GB limit is split into `install.swm`, `install2.swm`… the way Microsoft documents for
    FAT32 (`DISM /Split-Image`): every piece of it copied byte for byte, nothing unpacked. Windows Setup reads the parts
    by itself.
  - BIOS PCs start from our own boot code: an MBR and a FAT32 boot sector, written here in assembly
    (`imager/boot/*.S`), that load Windows' BOOTMGR the way Windows' own boot sector does. No boot code is taken from
    Windows or from another tool.
  - Windows 7's UEFI loader is only inside its ISO's UEFI boot image; it's copied out of it. Windows 7 still wants a PC
    with legacy boot (CSM) on and Secure Boot off, and the window says so.
  - **Windows 11 switches, each off unless ticked:** skip Setup's TPM 2.0, Secure Boot, processor and 4 GB RAM checks
    (Microsoft's LabConfig keys), and a local account instead of a Microsoft account (it has no password at first:
    Windows signs it in once by itself, then asks for a new password at the next sign-in). Ticked, they're written as an `autounattend.xml` at the stick's root; nothing else about Setup changes,
    and nothing in it chooses or erases a disk.
- **Windows on a DVD**: "On a DVD" burns the Windows ISO itself to a blank DVD, as it is (Windows 7 and 8.1 fit a
  4.7 GB DVD, Windows 10 needs a double-layer one, Windows 11 fits none), with macOS's `hdiutil burn` and the disc read
  back against the ISO, as Sofa Box OS's DVD is. Your own ISOs can be burned the same way.
- **Your own image.** An `.iso` that's also a disk (every Linux ISO now), an `.img`, or a packed `.img.xz`, written
  whole and read back against what was read. A Windows ISO is sent to Windows; an ISO that only starts from a DVD is
  refused, with why.
- `SofaBoxImager --inspect FILE` says what the Imager makes of a file (and, for a Windows ISO, the stick it would make);
  `--systems` lists the Linux list's newest releases as found on their sites now. Both only read.
- The disk rule is unchanged: one pure function, `DiskPolicy.refusals`, and only a removable, physical, whole disk is
  ever offered. Its words no longer assume Sofa Box OS.

**Proven, and how.** Every kind of media was written by the app's own `WriteJob` through a raw device to a disk image
and started in QEMU on this Mac (UEFI with OVMF and Microsoft's Secure Boot keys, and BIOS with SeaBIOS): Windows 11
(build 26300) and Windows 10 (22H2) from Microsoft's ISOs to Windows Setup both ways, Secure Boot read back as on from
inside Windows PE, the editions listed from the split parts, and the Windows 11 switch passing Setup's check in a PC
with no TPM. Then a whole Windows 11 install from the switches stick (UEFI, Secure Boot on, no TPM, no network):
Windows copied from the split parts, started from its own drive, the local account made with no Microsoft account and
no network, and its new password asked for at the second sign-in. Debian 13.7 (downloaded by the app from Debian) and Fedora 45 to their boot menus both ways; Raspberry Pi
OS Lite written and read back as Raspberry Pi's SHA-256 (a Pi can't be started in QEMU here). The imager README has
the details. **On real hardware**, once: the owner wrote Windows 11 to a 62 GB USB stick on an Intel Mac (macOS 13.7.8)
and installed it on a laptop from that stick ("it worked, tested on real hardware", 2026-11-15). No real SD card, Linux
stick or DVD yet.
