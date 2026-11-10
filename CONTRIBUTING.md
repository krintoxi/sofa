# Contributing to Sofa

Bug reports, fixes and improvements are welcome, for Sofa, Sofa Box OS, the TV apps and Sofa Box Imager.
Open an issue first for anything bigger than a fix, so nobody builds the same thing twice.

## Before you send a change

- Run the tests from the repository root: `python3 -m unittest discover -s tests -t . -v` (Python 3.9 and
  3.12 are what CI runs). A change to Sofa's code gets a new version and a line in `CHANGES.md`; a change
  under `deploy/sofa-box/` gets one in `deploy/sofa-box/CHANGES.md` (each file says how at the top).
- Nothing in the user interface may name a content source or carry an advertisement, tracker or account
  requirement, and no copied code from projects under licences that don't allow it.
- Pull requests say what was tested and on what (a Mac, a Pi 3 B+, a Fire TV...), and what wasn't.

## The contributor agreement

Sofa is published under the PolyForm Noncommercial License 1.0.0 (`LICENSE`): free for everyone's
noncommercial use, while EdgeVenture alone may offer it commercially, for example on a Sofa Box it sells.
For that to keep working once other people's code is in it, every contribution comes with this agreement.

By submitting a contribution (a pull request, a patch, a file, a translation, a design) to this
repository, you agree that:

1. **You have the right to submit it.** It is your own work, or you have permission to submit it under
   these terms, and it isn't copied from somewhere under a licence that forbids this.
2. **You keep your copyright**, and you grant EdgeVenture a perpetual, worldwide, non-exclusive,
   royalty-free, irrevocable licence to use, reproduce, change, combine, publish, distribute, sublicense
   and sell your contribution and works that include it, under the PolyForm Noncommercial License, under
   commercial terms, or under any other licence EdgeVenture chooses for the project in future.
3. **Patent licence.** If your contribution is covered by a patent you hold or control, you grant
   EdgeVenture and everyone who receives the software the same licence to it that the PolyForm
   Noncommercial License grants for the project's own patents.
4. **No warranty.** You provide the contribution as it is, with no promise that it works.

You confirm this by adding one line to your pull request's description or your commit message:

    I agree to the contributor agreement in CONTRIBUTING.md.

If you are contributing on behalf of an employer or another organisation, the line is theirs to give, by
someone who may give it. If these terms don't suit you, write to hello@edgeventure.uk before contributing.

## Names

"Sofa", "Sofa Box" and the logos are EdgeVenture's trademarks (`TRADEMARKS.md`). A fork you publish needs
another name.
