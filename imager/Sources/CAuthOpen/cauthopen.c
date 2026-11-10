// See include/cauthopen.h. Written for Sofa Box Imager from authopen(1)'s documented interface.
#include "cauthopen.h"

#include <Security/Authorization.h>
#include <Security/AuthorizationTags.h>
#include <errno.h>
#include <fcntl.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/disk.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;

static const char *AUTHOPEN = "/usr/libexec/authopen";

static int receive_fd(int sock) {
    char byte = 0;
    struct iovec iov = { .iov_base = &byte, .iov_len = 1 };
    union {
        struct cmsghdr align;
        char buf[CMSG_SPACE(sizeof(int))];
    } control;
    memset(&control, 0, sizeof(control));
    struct msghdr msg;
    memset(&msg, 0, sizeof(msg));
    msg.msg_iov = &iov;
    msg.msg_iovlen = 1;
    msg.msg_control = control.buf;
    msg.msg_controllen = sizeof(control.buf);
    ssize_t n;
    do {
        n = recvmsg(sock, &msg, 0);
    } while (n < 0 && errno == EINTR);
    if (n <= 0) return -1;
    for (struct cmsghdr *c = CMSG_FIRSTHDR(&msg); c != NULL; c = CMSG_NXTHDR(&msg, c)) {
        if (c->cmsg_level == SOL_SOCKET && c->cmsg_type == SCM_RIGHTS && c->cmsg_len >= CMSG_LEN(sizeof(int))) {
            int fd;
            memcpy(&fd, CMSG_DATA(c), sizeof(int));
            return fd;
        }
    }
    return -1;
}

int cauthopen_receive_from(const char *program, char *const argv[], const void *input, size_t input_len,
                           int *fd_out, int32_t *detail) {
    *fd_out = -1;
    *detail = 0;
    int status = CAUTHOPEN_FAILED;
    int sock[2] = { -1, -1 }, in[2] = { -1, -1 };
    pid_t pid = -1;
    posix_spawn_file_actions_t fa;
    posix_spawnattr_t attr;
    int haveFa = 0, haveAttr = 0;
    if (socketpair(AF_UNIX, SOCK_STREAM, 0, sock) != 0 || pipe(in) != 0) { *detail = errno; goto out; }
    if (posix_spawn_file_actions_init(&fa) != 0) { *detail = errno; goto out; }
    haveFa = 1;
    if (posix_spawnattr_init(&attr) != 0) { *detail = errno; goto out; }
    haveAttr = 1;
    // The helper gets only its stdin (the input), its stdout (the socket) and stderr; nothing else of ours.
    posix_spawnattr_setflags(&attr, POSIX_SPAWN_CLOEXEC_DEFAULT);
    posix_spawn_file_actions_adddup2(&fa, in[0], STDIN_FILENO);
    posix_spawn_file_actions_adddup2(&fa, sock[1], STDOUT_FILENO);
    posix_spawn_file_actions_addinherit_np(&fa, STDERR_FILENO);
    int rc = posix_spawn(&pid, program, &fa, &attr, argv, environ);
    if (rc != 0) { *detail = rc; pid = -1; goto out; }
    close(in[0]); in[0] = -1;
    close(sock[1]); sock[1] = -1;

    // The input first, then end of input.
    {
        const char *p = (const char *)input;
        size_t left = input_len;
        fcntl(in[1], F_SETNOSIGPIPE, 1);          // a helper that quit early mustn't kill us with SIGPIPE
        while (left > 0) {
            ssize_t w = write(in[1], p, left);
            if (w < 0 && errno == EINTR) continue;
            if (w <= 0) break;
            p += w;
            left -= (size_t)w;
        }
        close(in[1]); in[1] = -1;
    }
    int fd = receive_fd(sock[0]);
    int wstatus = 0;
    pid_t w;
    do {
        w = waitpid(pid, &wstatus, 0);
    } while (w < 0 && errno == EINTR);
    pid = -1;
    if (w < 0 || !WIFEXITED(wstatus) || WEXITSTATUS(wstatus) != 0) {
        // A descriptor from a helper that then failed isn't one to use.
        if (fd >= 0) close(fd);
        *detail = (w >= 0 && WIFEXITED(wstatus)) ? WEXITSTATUS(wstatus) : -1;
        goto out;
    }
    if (fd < 0) { *detail = EBADF; goto out; }
    *fd_out = fd;
    status = CAUTHOPEN_OK;

out:
    if (haveFa) posix_spawn_file_actions_destroy(&fa);
    if (haveAttr) posix_spawnattr_destroy(&attr);
    if (sock[0] >= 0) close(sock[0]);
    if (sock[1] >= 0) close(sock[1]);
    if (in[0] >= 0) close(in[0]);
    if (in[1] >= 0) close(in[1]);
    if (pid > 0) { int ws; while (waitpid(pid, &ws, 0) < 0 && errno == EINTR) {} }
    return status;
}

int cauthopen_open(const char *path, int oflags, const char *prompt, int interactive, int *fd_out, int32_t *detail) {
    *fd_out = -1;
    *detail = 0;
    char right[1100];
    if (snprintf(right, sizeof(right), "sys.openfile.readwrite.%s", path) >= (int)sizeof(right)) {
        *detail = ENAMETOOLONG;
        return CAUTHOPEN_FAILED;
    }
    AuthorizationItem item = { right, 0, NULL, 0 };
    AuthorizationRights rights = { 1, &item };
    AuthorizationItem envItem = { kAuthorizationEnvironmentPrompt, prompt ? strlen(prompt) : 0, (void *)prompt, 0 };
    AuthorizationEnvironment env = { prompt ? 1 : 0, prompt ? &envItem : NULL };
    AuthorizationFlags flags = kAuthorizationFlagExtendRights | kAuthorizationFlagPreAuthorize;
    if (interactive) flags |= kAuthorizationFlagInteractionAllowed;
    AuthorizationRef auth = NULL;
    OSStatus os = AuthorizationCreate(&rights, &env, flags, &auth);
    if (os != errAuthorizationSuccess) {
        *detail = os;
        if (auth) AuthorizationFree(auth, kAuthorizationFlagDestroyRights);
        return (os == errAuthorizationCanceled || os == errAuthorizationDenied || os == errAuthorizationInteractionNotAllowed)
            ? CAUTHOPEN_CANCELLED : CAUTHOPEN_FAILED;
    }
    AuthorizationExternalForm ext;
    os = AuthorizationMakeExternalForm(auth, &ext);
    if (os != errAuthorizationSuccess) {
        *detail = os;
        AuthorizationFree(auth, kAuthorizationFlagDestroyRights);
        return CAUTHOPEN_FAILED;
    }
    // authopen -stdoutpipe -extauth -o FLAGS PATH: it reads the authorization from stdin, opens PATH, and sends the
    // descriptor back over its stdout.
    char mode[16];
    snprintf(mode, sizeof(mode), "%d", oflags);
    char *argv[] = { (char *)AUTHOPEN, "-stdoutpipe", "-extauth", "-o", mode, (char *)path, NULL };
    int status = cauthopen_receive_from(AUTHOPEN, argv, ext.bytes, sizeof(ext.bytes), fd_out, detail);
    AuthorizationFree(auth, kAuthorizationFlagDestroyRights);
    return status;
}

int cauthopen_sync_disk(int fd) {
    dk_synchronize_t s;
    memset(&s, 0, sizeof(s));     // offset 0, length 0: the whole disk
    if (ioctl(fd, DKIOCSYNCHRONIZE, &s) != 0) return errno;
    return 0;
}

int cauthopen_geometry(int fd, uint32_t *block_size, uint64_t *block_count) {
    if (ioctl(fd, DKIOCGETBLOCKSIZE, block_size) != 0) return errno;
    if (ioctl(fd, DKIOCGETBLOCKCOUNT, block_count) != 0) return errno;
    return 0;
}
