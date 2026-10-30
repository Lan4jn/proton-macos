#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <Hypervisor/Hypervisor.h>

#define IPA_ALIGNED 0x20000000ULL
#define MAP_SIZE    65536ULL

static void emit_jsonl_vm_create(hv_return_t ret, int err) {
    printf("{\"event\":\"vm_create\",\"hv_return\":%u,\"hv_return_hex\":\"0x%08x\",\"errno\":%d,\"success\":%s}\n",
           ret, ret, err, (ret == HV_SUCCESS) ? "true" : "false");
    fflush(stdout);
}

static void emit_jsonl_vm_destroy(hv_return_t ret, int err) {
    printf("{\"event\":\"vm_destroy\",\"hv_return\":%u,\"hv_return_hex\":\"0x%08x\",\"errno\":%d,\"success\":%s}\n",
           ret, ret, err, (ret == HV_SUCCESS) ? "true" : "false");
    fflush(stdout);
}

typedef struct {
    const char *case_id;
    const char *description;
    const char *file_path;
    const char *file_access;
    int open_flags;
    int host_prot;
    const char *host_prot_str;
    int host_flags;
    const char *host_flags_str;
    hv_memory_flags_t hv_flags;
    const char *hv_flags_str;
} probe_case_def_t;

typedef struct {
    const char *case_id;
    const char *description;
    const char *file_path;
    const char *file_access;
    const char *host_prot_str;
    const char *host_flags_str;
    void *host_addr;
    size_t host_page_size;
    bool is_aligned;
    uint64_t ipa;
    size_t size;
    uint64_t hv_flags;
    const char *hv_flags_str;
    hv_return_t hv_map_return;
    int map_errno;
    bool hv_map_success;
    bool unmap_called;
    hv_return_t hv_unmap_return;
    int unmap_errno;
    bool hv_unmap_success;
    int munmap_return;
    int munmap_errno;
    const char *status;
} case_result_t;

static void emit_jsonl_case(const case_result_t *r) {
    char file_path_json[512];
    if (r->file_path) {
        snprintf(file_path_json, sizeof(file_path_json), "\"%s\"", r->file_path);
    } else {
        snprintf(file_path_json, sizeof(file_path_json), "null");
    }

    char unmap_ret_json[64];
    char unmap_hex_json[64];
    char unmap_success_json[16];
    if (r->unmap_called) {
        snprintf(unmap_ret_json, sizeof(unmap_ret_json), "%u", r->hv_unmap_return);
        snprintf(unmap_hex_json, sizeof(unmap_hex_json), "\"0x%08x\"", r->hv_unmap_return);
        snprintf(unmap_success_json, sizeof(unmap_success_json), "%s", r->hv_unmap_success ? "true" : "false");
    } else {
        snprintf(unmap_ret_json, sizeof(unmap_ret_json), "null");
        snprintf(unmap_hex_json, sizeof(unmap_hex_json), "null");
        snprintf(unmap_success_json, sizeof(unmap_success_json), "null");
    }

    printf("{\"event\":\"case_result\","
           "\"case_id\":\"%s\","
           "\"description\":\"%s\","
           "\"file_path\":%s,"
           "\"file_access\":\"%s\","
           "\"host_prot\":\"%s\","
           "\"host_flags\":\"%s\","
           "\"host_addr\":\"%p\","
           "\"host_page_size\":%zu,"
           "\"is_aligned\":%s,"
           "\"ipa\":\"0x%llx\","
           "\"size\":%zu,"
           "\"hv_flags\":%llu,"
           "\"hv_flags_hex\":\"0x%llx\","
           "\"hv_flags_str\":\"%s\","
           "\"hv_map_return\":%u,"
           "\"hv_map_return_hex\":\"0x%08x\","
           "\"map_errno\":%d,"
           "\"hv_map_success\":%s,"
           "\"unmap_called\":%s,"
           "\"hv_unmap_return\":%s,"
           "\"hv_unmap_return_hex\":%s,"
           "\"unmap_errno\":%d,"
           "\"hv_unmap_success\":%s,"
           "\"munmap_return\":%d,"
           "\"munmap_errno\":%d,"
           "\"status\":\"%s\"}\n",
           r->case_id,
           r->description,
           file_path_json,
           r->file_access,
           r->host_prot_str,
           r->host_flags_str,
           r->host_addr,
           r->host_page_size,
           r->is_aligned ? "true" : "false",
           (unsigned long long)r->ipa,
           r->size,
           (unsigned long long)r->hv_flags,
           (unsigned long long)r->hv_flags,
           r->hv_flags_str,
           r->hv_map_return,
           r->hv_map_return,
           r->map_errno,
           r->hv_map_success ? "true" : "false",
           r->unmap_called ? "true" : "false",
           unmap_ret_json,
           unmap_hex_json,
           r->unmap_errno,
           unmap_success_json,
           r->munmap_return,
           r->munmap_errno,
           r->status);
    fflush(stdout);
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <backing_seed_file>\n", argv[0]);
        return 1;
    }
    const char *backing_path = argv[1];

    size_t host_page_size = (size_t)getpagesize();

    // 1. Create Hypervisor VM instance
    errno = 0;
    hv_return_t create_ret = hv_vm_create(NULL);
    int create_err = errno;
    emit_jsonl_vm_create(create_ret, create_err);

    if (create_ret != HV_SUCCESS) {
        fprintf(stderr, "[ERROR] hv_vm_create failed: 0x%08x (errno=%d)\n", create_ret, create_err);
        return 2;
    }

    probe_case_def_t cases[4] = {
        {
            .case_id = "A",
            .description = "Anonymous host RW -> HV_READ|WRITE|EXEC positive control",
            .file_path = NULL,
            .file_access = "NONE",
            .open_flags = 0,
            .host_prot = PROT_READ | PROT_WRITE,
            .host_prot_str = "PROT_READ|PROT_WRITE",
            .host_flags = MAP_ANON | MAP_PRIVATE,
            .host_flags_str = "MAP_ANON|MAP_PRIVATE",
            .hv_flags = HV_MEMORY_READ | HV_MEMORY_WRITE | HV_MEMORY_EXEC,
            .hv_flags_str = "HV_MEMORY_READ|HV_MEMORY_WRITE|HV_MEMORY_EXEC"
        },
        {
            .case_id = "B",
            .description = "File O_RDONLY + host PROT_READ + MAP_SHARED -> HV_MEMORY_READ",
            .file_path = backing_path,
            .file_access = "O_RDONLY",
            .open_flags = O_RDONLY,
            .host_prot = PROT_READ,
            .host_prot_str = "PROT_READ",
            .host_flags = MAP_SHARED,
            .host_flags_str = "MAP_SHARED",
            .hv_flags = HV_MEMORY_READ,
            .hv_flags_str = "HV_MEMORY_READ"
        },
        {
            .case_id = "C",
            .description = "File O_RDONLY + host PROT_READ + MAP_SHARED -> HV_READ|WRITE|EXEC contrast",
            .file_path = backing_path,
            .file_access = "O_RDONLY",
            .open_flags = O_RDONLY,
            .host_prot = PROT_READ,
            .host_prot_str = "PROT_READ",
            .host_flags = MAP_SHARED,
            .host_flags_str = "MAP_SHARED",
            .hv_flags = HV_MEMORY_READ | HV_MEMORY_WRITE | HV_MEMORY_EXEC,
            .hv_flags_str = "HV_MEMORY_READ|HV_MEMORY_WRITE|HV_MEMORY_EXEC"
        },
        {
            .case_id = "D",
            .description = "File O_RDWR + host RW + MAP_SHARED -> HV_RWX positive control",
            .file_path = backing_path,
            .file_access = "O_RDWR",
            .open_flags = O_RDWR,
            .host_prot = PROT_READ | PROT_WRITE,
            .host_prot_str = "PROT_READ|PROT_WRITE",
            .host_flags = MAP_SHARED,
            .host_flags_str = "MAP_SHARED",
            .hv_flags = HV_MEMORY_READ | HV_MEMORY_WRITE | HV_MEMORY_EXEC,
            .hv_flags_str = "HV_MEMORY_READ|HV_MEMORY_WRITE|HV_MEMORY_EXEC"
        }
    };

    case_result_t results[4];
    memset(results, 0, sizeof(results));

    bool abort_further_cases = false;

    for (int i = 0; i < 4; i++) {
        probe_case_def_t *c = &cases[i];
        case_result_t *r = &results[i];

        r->case_id = c->case_id;
        r->description = c->description;
        r->file_path = c->file_path;
        r->file_access = c->file_access;
        r->host_prot_str = c->host_prot_str;
        r->host_flags_str = c->host_flags_str;
        r->host_page_size = host_page_size;
        r->ipa = IPA_ALIGNED;
        r->size = MAP_SIZE;
        r->hv_flags = c->hv_flags;
        r->hv_flags_str = c->hv_flags_str;

        if (abort_further_cases) {
            r->status = "SKIPPED_DUE_TO_PRIOR_ERROR";
            emit_jsonl_case(r);
            continue;
        }

        int fd = -1;
        if (c->file_path != NULL) {
            errno = 0;
            fd = open(c->file_path, c->open_flags);
            if (fd < 0) {
                r->map_errno = errno;
                r->status = "FILE_OPEN_FAILED";
                emit_jsonl_case(r);
                abort_further_cases = true;
                continue;
            }
        }

        // Host mmap without MAP_FIXED
        errno = 0;
        void *addr = mmap(NULL, MAP_SIZE, c->host_prot, c->host_flags, fd, 0);
        int mmap_err = errno;

        if (fd >= 0) {
            close(fd);
            fd = -1;
        }

        if (addr == MAP_FAILED) {
            r->host_addr = NULL;
            r->is_aligned = false;
            r->map_errno = mmap_err;
            r->status = "MMAP_FAILED";
            emit_jsonl_case(r);
            abort_further_cases = true;
            continue;
        }

        r->host_addr = addr;
        r->is_aligned = (((uintptr_t)addr % host_page_size) == 0);

        if (!r->is_aligned) {
            r->status = "HOST_ADDR_NOT_ALIGNED";
            munmap(addr, MAP_SIZE);
            emit_jsonl_case(r);
            abort_further_cases = true;
            continue;
        }

        // Invoke hv_vm_map
        errno = 0;
        hv_return_t map_ret = hv_vm_map(addr, IPA_ALIGNED, MAP_SIZE, c->hv_flags);
        int map_err = errno;

        r->hv_map_return = map_ret;
        r->map_errno = map_err;
        r->hv_map_success = (map_ret == HV_SUCCESS);

        if (r->hv_map_success) {
            // Only unmap if map succeeded
            r->unmap_called = true;
            errno = 0;
            hv_return_t unmap_ret = hv_vm_unmap(IPA_ALIGNED, MAP_SIZE);
            int unmap_err = errno;

            r->hv_unmap_return = unmap_ret;
            r->unmap_errno = unmap_err;
            r->hv_unmap_success = (unmap_ret == HV_SUCCESS);

            if (!r->hv_unmap_success) {
                // Unmap failed: resource state unknown! Stop immediately!
                r->status = "HV_UNMAP_FAILED";
                abort_further_cases = true;
            } else {
                r->status = "OK";
            }
        } else {
            // Map failed: do not call unmap
            r->unmap_called = false;
            r->status = "MAP_FAILED";
        }

        // Munmap host mapping
        errno = 0;
        int munmap_ret = munmap(addr, MAP_SIZE);
        r->munmap_return = munmap_ret;
        r->munmap_errno = errno;

        if (munmap_ret != 0) {
            r->status = "MUNMAP_FAILED";
            abort_further_cases = true;
        }

        emit_jsonl_case(r);
    }

    // 6. Destroy Hypervisor VM instance
    errno = 0;
    hv_return_t destroy_ret = hv_vm_destroy();
    int destroy_err = errno;
    emit_jsonl_vm_destroy(destroy_ret, destroy_err);

    // Final JSON summary
    printf("{\"event\":\"summary\",\"vm_create_ok\":%s,\"vm_destroy_ok\":%s,\"aborted\":%s}\n",
           (create_ret == HV_SUCCESS) ? "true" : "false",
           (destroy_ret == HV_SUCCESS) ? "true" : "false",
           abort_further_cases ? "true" : "false");
    fflush(stdout);

    return (abort_further_cases || destroy_ret != HV_SUCCESS) ? 3 : 0;
}
