# More room: the library on other drives

Sofa can keep part of the library on drives plugged into the Sofa computer (flash drives,
external SSDs and hard disks) and still show **one library**. A show can have Season 1 on the
computer and Season 2 on a drive; it's one show.

## Adding a drive

1. Plug it in. Within a few seconds it shows under **Server → Storage → Drives on this computer**.
2. Press **Use this drive**. Sofa makes a **Sofa Library** folder on it, with `Shows`, `Movies`,
   `Adult`, `Music` and `Music Videos` inside, laid out like the main ones
   ([folder-structure.md](folder-structure.md)).
3. Tick **Put new things from the Inbox here** if you want new arrivals to go to it.

You can also copy things into its folders yourself, in the usual layout; Sofa picks them up.

A drive that already has a Sofa library (from this or another computer) shows **Connect its
Sofa library** instead.

## Where new things go

**Server → Storage → New things go here** picks the place the Inbox files into. Two
exceptions, so nothing gets split up by accident:

- New episodes of a show that's already in the library go to wherever that show is.
- If the chosen drive isn't plugged in, new things go to this computer.

## Making room on this computer

Open a show or movie, press **Manage → Move it to another drive** and pick the drive. Sofa
copies it in the background (the progress is under Server → Storage), checks that the copy is
complete, then removes the original. Watch progress and My List stay as they were.

## Unplugging

A drive that's unplugged simply drops out: its shows and movies leave the library until it's
plugged in again, then they're back, with everyone's progress. Nothing is lost.

**Stop using** (Server → Storage) takes a drive out of the library for good. Nothing on the
drive is deleted.

## Good to know

- **Formats.** APFS or Mac OS Extended for a drive used only with this Mac; exFAT to share it with
  Windows too. **FAT32** can't hold files bigger than 4 GB (most movies are). **NTFS** (Windows)
  drives are read-only on a Mac: Sofa can play from them but can't put anything on them.
- **macOS permission.** If Sofa runs in the background (the usual way) and macOS doesn't let it
  open a drive, the Storage tab says so. The fix: **System Settings → Privacy & Security → Full
  Disk Access**, press **+**, press Command-Shift-G, paste the Python path the Storage tab shows,
  add it and switch it on, then restart Sofa.
- **Deleting and converting stay on the drive.** Something deleted from a drive goes to that
  drive's own `Sofa Library/Deleted`; originals of files converted to MP4 go to its own
  `Sofa Library/Converted Originals`. Nothing is copied across drives by surprise.
- A slow USB hard disk works, but the first time Sofa reads it, and making pictures and
  previews from it, take longer than on an SSD.
