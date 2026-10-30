#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/types.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/select.h>
#include <arpa/inet.h>
#include <time.h>

#define MAX_PACKET (16 * 1024 * 1024)
#define MAX_SEEN_KEYS 32

static uint64_t monotonic_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000 + (uint64_t)ts.tv_nsec / 1000000;
}

static uint32_t crc32_ieee(const uint8_t *data, size_t len) {
    uint32_t crc = ~0U;
    for (size_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (int k = 0; k < 8; k++) {
            crc = (crc >> 1) ^ (0xEDB88320U & -(crc & 1));
        }
    }
    return ~crc;
}

/* Non-blocking select loop with monotonic deadline and EINTR handling */
static int read_exact_deadline(int fd, uint8_t *buf, size_t len, uint64_t deadline_ms) {
    size_t off = 0;
    while (off < len) {
        uint64_t now = monotonic_ms();
        if (now >= deadline_ms) return -1;
        uint64_t remain_ms = deadline_ms - now;
        struct timeval tv;
        tv.tv_sec = (time_t)(remain_ms / 1000);
        tv.tv_usec = (suseconds_t)((remain_ms % 1000) * 1000);

        fd_set fds;
        FD_ZERO(&fds);
        FD_SET(fd, &fds);
        int r = select(fd + 1, &fds, NULL, NULL, &tv);
        if (r < 0) {
            if (errno == EINTR) continue;
            return -1;
        }
        if (r == 0) return -1; /* Timeout */

        ssize_t n = read(fd, buf + off, len - off);
        if (n < 0) {
            if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) continue;
            return -1;
        }
        if (n == 0) return -2; /* EOF */
        off += (size_t)n;
    }
    return 0;
}

static int write_exact_deadline(int fd, const uint8_t *buf, size_t len, uint64_t deadline_ms) {
    size_t off = 0;
    while (off < len) {
        uint64_t now = monotonic_ms();
        if (now >= deadline_ms) return -1;
        uint64_t remain_ms = deadline_ms - now;
        struct timeval tv;
        tv.tv_sec = (time_t)(remain_ms / 1000);
        tv.tv_usec = (suseconds_t)((remain_ms % 1000) * 1000);

        fd_set fds;
        FD_ZERO(&fds);
        FD_SET(fd, &fds);
        int r = select(fd + 1, NULL, &fds, NULL, &tv);
        if (r < 0) {
            if (errno == EINTR) continue;
            return -1;
        }
        if (r == 0) return -1; /* Timeout */

        ssize_t n = write(fd, buf + off, len - off);
        if (n < 0) {
            if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) continue;
            return -1;
        }
        if (n == 0) return -1;
        off += (size_t)n;
    }
    return 0;
}

/* Strict flat JSON tokenizer & validator */
typedef enum { JSON_STR, JSON_INT } json_type_t;
typedef struct {
    char key[32];
    json_type_t type;
    char str_val[128];
    int64_t int_val;
    int present;
} json_field_t;

static int parse_flat_json(const char *json_str, json_field_t *fields, size_t num_fields) {
    for (size_t i = 0; i < num_fields; i++) fields[i].present = 0;
    char seen_keys[MAX_SEEN_KEYS][32];
    size_t num_seen_keys = 0;

    const char *p = json_str;
    while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') p++;
    if (*p != '{') return -1;
    p++;
    int closed = 0;

    while (*p) {
        while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') p++;
        if (*p == '}') {
            closed = 1;
            p++;
            break;
        }
        if (*p != '"') return -1;
        p++;
        const char *k_start = p;
        while (*p && *p != '"') p++;
        if (*p != '"') return -1;
        size_t k_len = (size_t)(p - k_start);
        if (k_len >= 32) return -1;
        char cur_key[32];
        memcpy(cur_key, k_start, k_len);
        cur_key[k_len] = '\0';
        p++; /* skip '"' */

        /* 严格检查所有字段（含未知字段）的重复 key 违规 */
        for (size_t s = 0; s < num_seen_keys; s++) {
            if (strcmp(seen_keys[s], cur_key) == 0) return -1; /* Duplicate key rejected */
        }
        if (num_seen_keys < MAX_SEEN_KEYS) {
            strcpy(seen_keys[num_seen_keys++], cur_key);
        } else {
            return -1; /* Too many keys */
        }

        while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') p++;
        if (*p != ':') return -1;
        p++; /* skip ':' */
        while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') p++;

        int matched = -1;
        for (size_t i = 0; i < num_fields; i++) {
            if (strcmp(fields[i].key, cur_key) == 0) {
                matched = (int)i;
                break;
            }
        }

        if (*p == '"') {
            /* String value */
            p++;
            const char *v_start = p;
            while (*p && *p != '"') p++;
            if (*p != '"') return -1;
            size_t v_len = (size_t)(p - v_start);
            p++; /* skip '"' */
            if (matched >= 0) {
                if (fields[matched].type != JSON_STR) return -1; /* Type mismatch (expected int) */
                if (v_len >= sizeof(fields[matched].str_val)) return -1;
                memcpy(fields[matched].str_val, v_start, v_len);
                fields[matched].str_val[v_len] = '\0';
                fields[matched].present = 1;
            }
        } else {
            /* Number or boolean or decimal/float value */
            const char *v_start = p;
            int is_decimal = 0;
            if (*p == '-') p++;
            while ((*p >= '0' && *p <= '9') || *p == '.') {
                if (*p == '.') is_decimal = 1;
                p++;
            }
            size_t v_len = (size_t)(p - v_start);
            if (v_len == 0) {
                /* check true / false / null */
                if (strncmp(p, "true", 4) == 0) { p += 4; v_len = 4; }
                else if (strncmp(p, "false", 5) == 0) { p += 5; v_len = 5; }
                else if (strncmp(p, "null", 4) == 0) { p += 4; v_len = 4; }
                else return -1;
            }
            if (matched >= 0) {
                if (fields[matched].type != JSON_INT) return -1; /* Type mismatch (expected str) */
                if (is_decimal) return -1; /* Expected integer, got decimal float */
                char tmp[32];
                if (v_len >= sizeof(tmp)) return -1;
                memcpy(tmp, v_start, v_len);
                tmp[v_len] = '\0';
                errno = 0;
                char *endp = NULL;
                fields[matched].int_val = strtoll(tmp, &endp, 10);
                if (errno == ERANGE || !endp || *endp != '\0') return -1;
                fields[matched].present = 1;
            }
        }
        while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') p++;
        if (*p == ',') { p++; continue; }
        if (*p == '}') {
            closed = 1;
            p++;
            break;
        }
        return -1;
    }
    if (!closed) return -1; /* 缺少右大括号报错 */
    while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') p++;
    if (*p != '\0') return -1; /* 尾随垃圾字符报错 */
    return 0;
}

static int recv_packet(int fd, char *json_out, size_t max_json, uint64_t deadline_ms) {
    uint32_t total_be, json_be;
    if (read_exact_deadline(fd, (uint8_t *)&total_be, 4, deadline_ms) < 0) return -1;
    uint32_t total = ntohl(total_be);
    if (total < 4 || total > MAX_PACKET) return -1;
    if (read_exact_deadline(fd, (uint8_t *)&json_be, 4, deadline_ms) < 0) return -1;
    uint32_t jlen = ntohl(json_be);
    if (jlen < 2 || jlen > total - 4 || jlen >= max_json) return -1;
    if (read_exact_deadline(fd, (uint8_t *)json_out, jlen, deadline_ms) < 0) return -1;
    json_out[jlen] = '\0';
    uint32_t payload_len = total - 4 - jlen;
    if (payload_len > 0) return -2; /* ACK must carry zero payload */
    return 0;
}

static int send_packet(int fd, const char *json_str, const uint8_t *payload, uint32_t payload_len, uint64_t deadline_ms) {
    uint32_t jlen = (uint32_t)strlen(json_str);
    uint32_t total = 4 + jlen + payload_len;
    uint32_t total_be = htonl(total);
    uint32_t jlen_be = htonl(jlen);
    if (write_exact_deadline(fd, (uint8_t *)&total_be, 4, deadline_ms) < 0) return -1;
    if (write_exact_deadline(fd, (uint8_t *)&jlen_be, 4, deadline_ms) < 0) return -1;
    if (write_exact_deadline(fd, (const uint8_t *)json_str, jlen, deadline_ms) < 0) return -1;
    if (payload_len > 0 && payload) {
        if (write_exact_deadline(fd, payload, payload_len, deadline_ms) < 0) return -1;
    }
    return 0;
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "Usage: guest_producer <socket_path> [mode]\n");
        return 1;
    }
    const char *sock_path = argv[1];
    if (strlen(sock_path) >= 104) {
        fprintf(stderr, "Socket path exceeds 104 bytes\n");
        return 1;
    }

    int sock = socket(AF_UNIX, SOCK_STREAM, 0);
    if (sock < 0) return 2;

    int flags = fcntl(sock, F_GETFL, 0);
    if (flags < 0 || fcntl(sock, F_SETFL, flags | O_NONBLOCK) < 0) {
        close(sock);
        return 2;
    }

    struct sockaddr_un addr;
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, sock_path, sizeof(addr.sun_path) - 1);

    uint64_t connect_deadline = monotonic_ms() + 4000;
    int connected = 0;
    while (monotonic_ms() < connect_deadline) {
        int r = connect(sock, (struct sockaddr *)&addr, sizeof(addr));
        if (r == 0) { connected = 1; break; }
        if (errno == EISCONN) { connected = 1; break; }
        if (errno == EINPROGRESS || errno == EALREADY || errno == EWOULDBLOCK) {
            uint64_t now = monotonic_ms();
            if (now >= connect_deadline) break;
            struct timeval tv;
            tv.tv_sec = (time_t)((connect_deadline - now) / 1000);
            tv.tv_usec = (suseconds_t)(((connect_deadline - now) % 1000) * 1000);
            fd_set wset;
            FD_ZERO(&wset);
            FD_SET(sock, &wset);
            int sr = select(sock + 1, NULL, &wset, NULL, &tv);
            if (sr > 0) {
                int err = 0;
                socklen_t elen = sizeof(err);
                if (getsockopt(sock, SOL_SOCKET, SO_ERROR, &err, &elen) == 0 && err == 0) {
                    connected = 1;
                    break;
                }
            }
        }
        struct timespec dly = {0, 10000000};
        nanosleep(&dly, NULL);
    }
    if (!connected) {
        close(sock);
        return 3;
    }

    /* 1. Send CREATE */
    const char *create_json = "{\"v\":1,\"sid\":1,\"gen\":1,\"w\":1280,\"h\":720,\"pitch\":5120,\"format\":\"RGBA8\",\"type\":\"CREATE\"}";
    if (send_packet(sock, create_json, NULL, 0, monotonic_ms() + 3000) < 0) { close(sock); return 4; }

    char ack_buf[4096];
    if (recv_packet(sock, ack_buf, sizeof(ack_buf), monotonic_ms() + 4000) < 0) { close(sock); return 5; }

    json_field_t create_fields[] = {
        {"v", JSON_INT, {0}, 0, 0},
        {"type", JSON_STR, {0}, 0, 0},
        {"ack_for", JSON_STR, {0}, 0, 0},
        {"stage", JSON_STR, {0}, 0, 0},
        {"sid", JSON_INT, {0}, 0, 0},
        {"gen", JSON_INT, {0}, 0, 0}
    };
    if (parse_flat_json(ack_buf, create_fields, 6) < 0) { close(sock); return 6; }
    if (!create_fields[0].present || create_fields[0].int_val != 1) { close(sock); return 6; }
    if (!create_fields[1].present || strcmp(create_fields[1].str_val, "ACK") != 0) { close(sock); return 6; }
    if (!create_fields[2].present || strcmp(create_fields[2].str_val, "CREATE") != 0) { close(sock); return 6; }
    if (!create_fields[3].present || strcmp(create_fields[3].str_val, "CONFIGURED") != 0) { close(sock); return 6; }
    if (!create_fields[4].present || create_fields[4].int_val != 1) { close(sock); return 6; }
    if (!create_fields[5].present || create_fields[5].int_val != 1) { close(sock); return 6; }

    /* 2. Send Frame 1 */
    size_t payload_len = 1280 * 720 * 4;
    uint8_t *frame = malloc(payload_len);
    if (!frame) { close(sock); return 7; }
    for (size_t i = 0; i < payload_len; i += 4) {
        frame[i] = 11; frame[i+1] = 37; frame[i+2] = 89; frame[i+3] = 255;
    }
    uint32_t crc = crc32_ieee(frame, payload_len);

    char frame_hdr[256];
    snprintf(frame_hdr, sizeof(frame_hdr),
             "{\"v\":1,\"sid\":1,\"gen\":1,\"w\":1280,\"h\":720,\"pitch\":5120,\"format\":\"RGBA8\",\"type\":\"FRAME\",\"seq\":1,\"payload_bytes\":%u,\"crc32\":%u,\"capture\":false}",
             (unsigned)payload_len, (unsigned)crc);
    if (send_packet(sock, frame_hdr, frame, (uint32_t)payload_len, monotonic_ms() + 3000) < 0) {
        free(frame); close(sock); return 8;
    }
    free(frame);

    /* Recv RECEIVED */
    if (recv_packet(sock, ack_buf, sizeof(ack_buf), monotonic_ms() + 4000) < 0) { close(sock); return 9; }
    json_field_t recv_fields[] = {
        {"v", JSON_INT, {0}, 0, 0},
        {"type", JSON_STR, {0}, 0, 0},
        {"ack_for", JSON_STR, {0}, 0, 0},
        {"stage", JSON_STR, {0}, 0, 0},
        {"sid", JSON_INT, {0}, 0, 0},
        {"gen", JSON_INT, {0}, 0, 0},
        {"seq", JSON_INT, {0}, 0, 0},
        {"slot", JSON_INT, {0}, 0, 0},
        {"crc32", JSON_INT, {0}, 0, 0}
    };
    if (parse_flat_json(ack_buf, recv_fields, 9) < 0) { close(sock); return 10; }
    if (!recv_fields[0].present || recv_fields[0].int_val != 1) { close(sock); return 10; }
    if (!recv_fields[1].present || strcmp(recv_fields[1].str_val, "ACK") != 0) { close(sock); return 10; }
    if (!recv_fields[2].present || strcmp(recv_fields[2].str_val, "FRAME") != 0) { close(sock); return 10; }
    if (!recv_fields[3].present || strcmp(recv_fields[3].str_val, "RECEIVED") != 0) { close(sock); return 10; }
    if (!recv_fields[4].present || recv_fields[4].int_val != 1) { close(sock); return 10; }
    if (!recv_fields[5].present || recv_fields[5].int_val != 1) { close(sock); return 10; }
    if (!recv_fields[6].present || recv_fields[6].int_val != 1) { close(sock); return 10; }
    if (!recv_fields[7].present || (recv_fields[7].int_val != 0 && recv_fields[7].int_val != 1)) { close(sock); return 10; }
    if (!recv_fields[8].present || (uint32_t)recv_fields[8].int_val != crc) { close(sock); return 10; }
    int received_slot = (int)recv_fields[7].int_val;

    /* Recv CONSUMED */
    if (recv_packet(sock, ack_buf, sizeof(ack_buf), monotonic_ms() + 4000) < 0) { close(sock); return 11; }
    json_field_t term_fields[] = {
        {"v", JSON_INT, {0}, 0, 0},
        {"type", JSON_STR, {0}, 0, 0},
        {"ack_for", JSON_STR, {0}, 0, 0},
        {"stage", JSON_STR, {0}, 0, 0},
        {"sid", JSON_INT, {0}, 0, 0},
        {"gen", JSON_INT, {0}, 0, 0},
        {"seq", JSON_INT, {0}, 0, 0},
        {"slot", JSON_INT, {0}, 0, 0},
        {"crc32", JSON_INT, {0}, 0, 0},
        {"disposition", JSON_STR, {0}, 0, 0}
    };
    if (parse_flat_json(ack_buf, term_fields, 10) < 0) { close(sock); return 12; }
    if (!term_fields[0].present || term_fields[0].int_val != 1) { close(sock); return 12; }
    if (!term_fields[1].present || strcmp(term_fields[1].str_val, "ACK") != 0) { close(sock); return 12; }
    if (!term_fields[2].present || strcmp(term_fields[2].str_val, "FRAME") != 0) { close(sock); return 12; }
    if (!term_fields[3].present || strcmp(term_fields[3].str_val, "CONSUMED") != 0) { close(sock); return 12; }
    if (!term_fields[4].present || term_fields[4].int_val != 1) { close(sock); return 12; }
    if (!term_fields[5].present || term_fields[5].int_val != 1) { close(sock); return 12; }
    if (!term_fields[6].present || term_fields[6].int_val != 1) { close(sock); return 12; }
    if (!term_fields[7].present || term_fields[7].int_val != received_slot) { close(sock); return 12; } /* 配对一致 */
    if (!term_fields[8].present || (uint32_t)term_fields[8].int_val != crc) { close(sock); return 12; }
    if (!term_fields[9].present) { close(sock); return 12; }
    if (strcmp(term_fields[9].str_val, "displayed") != 0 &&
        strcmp(term_fields[9].str_val, "replaced") != 0 &&
        strcmp(term_fields[9].str_val, "invalidated") != 0) { close(sock); return 12; }

    /* 3. Send CLOSE */
    if (send_packet(sock, "{\"v\":1,\"sid\":1,\"type\":\"CLOSE\"}", NULL, 0, monotonic_ms() + 3000) < 0) { close(sock); return 13; }
    if (recv_packet(sock, ack_buf, sizeof(ack_buf), monotonic_ms() + 4000) < 0) { close(sock); return 14; }
    json_field_t close_fields[] = {
        {"v", JSON_INT, {0}, 0, 0},
        {"type", JSON_STR, {0}, 0, 0},
        {"ack_for", JSON_STR, {0}, 0, 0},
        {"stage", JSON_STR, {0}, 0, 0}
    };
    if (parse_flat_json(ack_buf, close_fields, 4) < 0) { close(sock); return 15; }
    if (!close_fields[2].present || strcmp(close_fields[2].str_val, "CLOSE") != 0) { close(sock); return 15; }
    if (!close_fields[3].present || strcmp(close_fields[3].str_val, "CLOSED") != 0) { close(sock); return 15; }

    close(sock);
    return 0;
}
