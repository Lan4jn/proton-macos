#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#include <string.h>
#include <fcntl.h>
#include <poll.h>
#include <errno.h>

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "Usage: wine_readiness_probe <prefix_dir>\n");
        return 1;
    }
    const char *prefix = argv[1];
    struct stat st;
    if (stat(prefix, &st) == -1) {
        printf("{\"status\":\"FAIL\",\"error\":\"stat_prefix_failed\",\"errno\":%d}\n", errno);
        return 2;
    }
    uid_t uid = getuid();
    gid_t gid = getgid();

    char socket_path[1024];
    snprintf(socket_path, sizeof(socket_path), "/tmp/.wine-%u/server-%llx-%llx/socket",
             (unsigned int)uid, (unsigned long long)st.st_dev, (unsigned long long)st.st_ino);

    struct stat sock_st;
    if (lstat(socket_path, &sock_st) == -1) {
        printf("{\"status\":\"WAITING\",\"uid\":%u,\"gid\":%u,\"dev\":\"%llx\",\"ino\":\"%llx\",\"socket_path\":\"%s\",\"error\":\"socket_absent\",\"errno\":%d}\n",
               (unsigned int)uid, (unsigned int)gid, (unsigned long long)st.st_dev, (unsigned long long)st.st_ino, socket_path, errno);
        return 3;
    }

    if (!S_ISSOCK(sock_st.st_mode)) {
        printf("{\"status\":\"FAIL\",\"error\":\"not_a_socket\",\"socket_path\":\"%s\"}\n", socket_path);
        return 4;
    }

    int s = socket(AF_UNIX, SOCK_STREAM, 0);
    if (s == -1) {
        printf("{\"status\":\"FAIL\",\"error\":\"socket_call_failed\",\"errno\":%d}\n", errno);
        return 5;
    }

    /* Set non-blocking mode on socket */
    int flags = fcntl(s, F_GETFL, 0);
    if (flags != -1) fcntl(s, F_SETFL, flags | O_NONBLOCK);

    struct sockaddr_un addr;
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, socket_path, sizeof(addr.sun_path) - 1);

    int ret = connect(s, (struct sockaddr *)&addr, sizeof(addr));
    if (ret == -1) {
        if (errno == EINPROGRESS) {
            struct pollfd pfd;
            pfd.fd = s;
            pfd.events = POLLOUT;
            int pr = poll(&pfd, 1, 500); /* 500ms deadline */
            if (pr > 0 && (pfd.revents & POLLOUT)) {
                int err = 0;
                socklen_t elen = sizeof(err);
                if (getsockopt(s, SOL_SOCKET, SO_ERROR, &err, &elen) == 0 && err == 0) {
                    close(s);
                    printf("{\"status\":\"READY\",\"uid\":%u,\"gid\":%u,\"dev\":\"%llx\",\"ino\":\"%llx\",\"socket_path\":\"%s\"}\n",
                           (unsigned int)uid, (unsigned int)gid, (unsigned long long)st.st_dev, (unsigned long long)st.st_ino, socket_path);
                    return 0;
                }
            }
        }
        int err = errno;
        close(s);
        printf("{\"status\":\"WAITING\",\"uid\":%u,\"gid\":%u,\"dev\":\"%llx\",\"ino\":\"%llx\",\"socket_path\":\"%s\",\"error\":\"connect_failed\",\"errno\":%d}\n",
               (unsigned int)uid, (unsigned int)gid, (unsigned long long)st.st_dev, (unsigned long long)st.st_ino, socket_path, err);
        return 6;
    }

    close(s);
    printf("{\"status\":\"READY\",\"uid\":%u,\"gid\":%u,\"dev\":\"%llx\",\"ino\":\"%llx\",\"socket_path\":\"%s\"}\n",
           (unsigned int)uid, (unsigned int)gid, (unsigned long long)st.st_dev, (unsigned long long)st.st_ino, socket_path);
    return 0;
}
