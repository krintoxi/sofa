// Opening a raw disk through macOS's own authopen (which shows macOS's admin password prompt), and two ioctls Swift
// can't spell. No privileged helper is installed: authopen opens the disk and hands the descriptor back.
#ifndef CAUTHOPEN_H
#define CAUTHOPEN_H

#include <stddef.h>
#include <stdint.h>

enum {
    CAUTHOPEN_OK = 0,
    CAUTHOPEN_CANCELLED = 1,   // the owner cancelled the password prompt, or isn't an administrator
    CAUTHOPEN_FAILED = 2,      // authopen couldn't be run, or sent no descriptor back (see *detail)
};

// Asks for the right to open `path` read-write, then has /usr/libexec/authopen open it with `oflags` and send the
// descriptor back over a socket (authopen -stdoutpipe -extauth -o FLAGS PATH). `prompt` is shown in macOS's own
// password dialog. With `interactive` 0 no dialog is shown (tests: it fails unless the right is already held).
// On CAUTHOPEN_OK, *fd_out is the open descriptor (the caller closes it). *detail gets an OSStatus or errno.
int cauthopen_open(const char *path, int oflags, const char *prompt, int interactive, int *fd_out, int32_t *detail);

// The second half of cauthopen_open, on its own so it can be tested without a password: runs `program` with `argv`
// (NULL-terminated), giving it `input` on its stdin and a socket as its stdout, and receives the one descriptor it
// sends back (SCM_RIGHTS), as `authopen -stdoutpipe` does. The program inherits nothing else of ours but stderr.
// A descriptor from a program that then exits with an error is closed, not returned.
int cauthopen_receive_from(const char *program, char *const argv[], const void *input, size_t input_len,
                           int *fd_out, int32_t *detail);

// Asks the disk to write out its own cache (DKIOCSYNCHRONIZE). Returns 0, or errno (ENOTTY where a disk doesn't take it).
int cauthopen_sync_disk(int fd);

// The open disk's sector size and sector count (DKIOCGETBLOCKSIZE, DKIOCGETBLOCKCOUNT). Returns 0 or errno.
int cauthopen_geometry(int fd, uint32_t *block_size, uint64_t *block_count);

#endif
