#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

static void die(const char *what) { perror(what); exit(2); }
static void *writer(void *p) { *(volatile unsigned char *)p = 0x55; return NULL; }

int main(int argc, char **argv) {
    const char *names[] = {"shared", "private", "lanes", "fixed", "protect", "thread", "fork-private", "fork-shared", "remap"};
    int id = -1;
    if (argc != 3 || getenv("ELFUSE_DIAG_SESSION_SHARED")) {
        fprintf(stderr, "usage: probe CASE LANE; diagnostic gate must be absent\n"); return 2;
    }
    for (int i = 0; i < 9; i++) if (!strcmp(argv[1], names[i])) id = i;
    char *end;
    unsigned long value = strtoul(argv[2], &end, 10);
    long page = sysconf(_SC_PAGESIZE);
    if (id < 0 || *end || (value != 4096 && value != 16384) || page <= 0) return 2;
    size_t lane = value, len = lane * 4;
    if ((id == 3 || id == 4 || id == 8) && lane % (size_t)page) {
        printf("{\"case\":\"%s\",\"lane\":%zu,\"page_size\":%ld,\"status\":\"UNSUPPORTED_ALIGNMENT\"}\n", names[id], lane, page);
        return 77;
    }
    char path[] = "cow-matrix-XXXXXX";
    int fd = mkstemp(path);
    if (fd < 0) die("mkstemp");
    if (unlink(path)) die("unlink owned backing");
    unsigned char *initial = malloc(len), *file = malloc(len);
    if (!initial || !file) die("malloc");
    for (size_t i = 0; i < len; i++) initial[i] = (unsigned char)(0x10 + i / lane);
    if (write(fd, initial, len) != (ssize_t)len) die("write backing");
    int shared = id == 0 || id == 3 || id == 4 || id == 7 || id == 8;
    unsigned char *a = mmap(NULL, len, PROT_READ|PROT_WRITE, shared ? MAP_SHARED : MAP_PRIVATE, fd, 0);
    unsigned char *b = mmap(NULL, len, PROT_READ|PROT_WRITE, MAP_SHARED, fd, 0);
    unsigned char *s = mmap(NULL, len, PROT_READ|PROT_WRITE, MAP_PRIVATE, fd, 0);
    if (a == MAP_FAILED || b == MAP_FAILED || s == MAP_FAILED) die("mmap");
    /* Dirty the private sibling before changing backing: external updates to
       an untouched MAP_PRIVATE mapping have unspecified POSIX visibility. */
    s[lane] = initial[lane];
    int expected_file = shared ? 0x55 : 0x11;
    int expected_target = 0x55, child_seen = -1;
    if (id == 3) {
        if (mmap(a + lane, lane, PROT_READ|PROT_WRITE, MAP_PRIVATE|MAP_FIXED, fd, (off_t)lane) != a + lane) die("MAP_FIXED");
        expected_file = 0x11;
    }
    if (id == 4) {
        if (mprotect(a + lane, lane, PROT_READ)) die("mprotect RO");
        if (mprotect(a + lane, lane, PROT_READ|PROT_WRITE)) die("mprotect RW");
    }
    if (id == 5) {
        pthread_t t;
        int e = pthread_create(&t, NULL, writer, a + lane);
        if (e) { errno=e; die("pthread_create"); }
        e=pthread_join(t, NULL);
        if (e) { errno=e; die("pthread_join"); }
    } else if (id == 6 || id == 7) {
        int channel[2];
        if (pipe(channel)) die("pipe");
        pid_t pid = fork();
        if (pid < 0) die("fork");
        if (!pid) {
            close(channel[0]);
            volatile unsigned char *target = a + lane;
            *target = 0x55;
            unsigned char seen = *target;
            _exit(write(channel[1], &seen, 1) == 1 ? 0 : 2);
        }
        close(channel[1]);
        unsigned char seen;
        ssize_t nr;
        do { nr = read(channel[0], &seen, 1); } while (nr < 0 && errno == EINTR);
        if (nr != 1) die("child observation");
        close(channel[0]);
        child_seen = seen;
        int st;
        if (waitpid(pid, &st, 0) != pid) die("waitpid");
        if (!WIFEXITED(st) || WEXITSTATUS(st)) return 2;
        if (id == 6) expected_target=0x11;
    } else {
        a[lane] = 0x55;
    }
    if (id == 8) {
        if (munmap(a + lane, lane)) die("munmap lane");
        if (mmap(a + lane, lane, PROT_READ|PROT_WRITE, MAP_PRIVATE|MAP_FIXED, fd, (off_t)lane) != a + lane) die("remap lane");
        a[lane] = 0x66;
        expected_target=0x66;
        expected_file=0x55;
    }
    /* Neighbor shared visibility is tested after splitting/replacing the target. */
    int neighbor_value = initial[0];
    if (shared) { b[0] = 0x77; b[2*lane] = 0x78; neighbor_value=0x77; }
    if (msync(a, len, MS_SYNC)) die("msync");
    if (pread(fd, file, len, 0) != (ssize_t)len) die("pread");
    int file_ok = 1, sibling_ok = 1, neighbor_ok = 1;
    for (size_t i=0; i<len; i++) {
        int want = initial[i];
        if (i==lane) want=expected_file;
        if (shared && i==0) want=0x77;
        if (shared && i==2*lane) want=0x78;
        if (file[i] != want || b[i] != want) file_ok=0;
        /* Private sibling must not see this mapping's private write. File updates
           after mmap are deliberately not asserted as a universal POSIX promise. */
        if (!shared && s[i] != initial[i]) sibling_ok=0;
        if (i < lane || i >= 2*lane) {
            int nw=initial[i];
            if (shared && i==0) nw=0x77;
            if (shared && i==2*lane) nw=0x78;
            if (a[i] != nw) neighbor_ok=0;
        }
    }
    if (a[lane] != expected_target) neighbor_ok=0;
    if (s[lane] != 0x11) sibling_ok=0;
    if (child_seen != -1 && child_seen != 0x55) sibling_ok=0;
    printf("{\"child_write_seen\":%d,\"case\":\"%s\",\"lane\":%zu,\"page_size\":%ld,\"status\":\"%s\",\"observed\":{\"file\":%u,\"sibling\":%u,\"target\":%u,\"neighbor\":%u},\"expected\":{\"file\":%d,\"target\":%d,\"neighbor\":%d},\"assertions\":{\"file\":%s,\"sibling\":%s,\"neighbor\":%s}}\n", child_seen, names[id], lane, page,
        file_ok && sibling_ok && neighbor_ok ? "PASS" : "FAIL", file[lane],s[lane],a[lane],a[0],expected_file,expected_target,neighbor_value,
        file_ok?"true":"false",sibling_ok?"true":"false",neighbor_ok?"true":"false");
    if (munmap(a,len) || munmap(b,len) || munmap(s,len) || close(fd)) die("cleanup");
    free(initial); free(file);
    return file_ok && sibling_ok && neighbor_ok ? 0 : 1;
}
