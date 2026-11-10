// A stand-in for /usr/libexec/authopen, for the tests only (it isn't part of the app): it takes authopen's own
// arguments (-stdoutpipe -extauth -o FLAGS PATH), reads the 32-byte authorization from stdin, opens PATH with no
// authorization at all, and sends the descriptor back over stdout, as authopen -stdoutpipe does. So the tests can
// check Sofa Box Imager's side of that conversation without a password.
//
//   PATH ending in ".exit1":   send the descriptor, then exit 1 (an authopen that failed after opening).
//   PATH ending in ".silent":  send nothing, exit 0.
// It also exits 3 if it was handed any descriptor beyond stdin, stdout and stderr.
#include <errno.h>
#include <fcntl.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

static int ends_with(const char *s, const char *suffix) {
    size_t a = strlen(s), b = strlen(suffix);
    return a >= b && strcmp(s + a - b, suffix) == 0;
}

int main(int argc, char **argv) {
    if (argc != 6 || strcmp(argv[1], "-stdoutpipe") != 0 || strcmp(argv[2], "-extauth") != 0 || strcmp(argv[3], "-o") != 0) {
        return 64;
    }
    for (int fd = 3; fd < 256; fd++) {
        if (fcntl(fd, F_GETFD) != -1 || errno != EBADF) return 3;
    }
    char auth[64];
    size_t got = 0;
    for (;;) {
        ssize_t n = read(STDIN_FILENO, auth + got, sizeof(auth) - got);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) break;
        got += (size_t)n;
        if (got == sizeof(auth)) break;
    }
    if (got != 32) return 2;                       // sizeof(AuthorizationExternalForm)
    const char *path = argv[5];
    if (ends_with(path, ".silent")) return 0;
    int fd = open(path, atoi(argv[4]));
    if (fd < 0) return 1;
    char byte = 0;
    struct iovec iov = { &byte, 1 };
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
    struct cmsghdr *c = CMSG_FIRSTHDR(&msg);
    c->cmsg_level = SOL_SOCKET;
    c->cmsg_type = SCM_RIGHTS;
    c->cmsg_len = CMSG_LEN(sizeof(int));
    memcpy(CMSG_DATA(c), &fd, sizeof(int));
    if (sendmsg(STDOUT_FILENO, &msg, 0) < 0) return 1;
    return ends_with(path, ".exit1") ? 1 : 0;
}
