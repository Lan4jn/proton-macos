#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include <errno.h>

/* Replicate the exact logic from net-absock.c for standalone unit testing */
static int absock_validate_custom_base(const char *base, char *clean_out, size_t clean_sz)
{
    if (!base || base[0] != '/') {
        errno = EINVAL;
        return -1;
    }

    size_t len = strlen(base);
    if (len == 0 || len >= 60) {
        errno = (len >= 60) ? ENAMETOOLONG : EINVAL;
        return -1;
    }

    /* Strip any trailing slashes FIRST so lstat inspects the leaf link itself,
     * not the link target (macOS lstat on a path with a trailing slash follows symlinks!).
     */
    size_t blen = len;
    while (blen > 1 && base[blen - 1] == '/')
        blen--;

    if (blen >= clean_sz) {
        errno = ENAMETOOLONG;
        return -1;
    }
    memcpy(clean_out, base, blen);
    clean_out[blen] = '\0';

    struct stat st;
    if (lstat(clean_out, &st) < 0)
        return -1;

    if (S_ISLNK(st.st_mode)) {
        errno = ELOOP;
        return -1;
    }

    if (!S_ISDIR(st.st_mode)) {
        errno = ENOTDIR;
        return -1;
    }

    if (st.st_uid != getuid() || (st.st_mode & (S_IRWXG | S_IRWXO)) != 0) {
        errno = EACCES;
        return -1;
    }

    return 0;
}

static int absock_dir_format(char *out, size_t out_sz, uint64_t namespace_id)
{
    const char *custom_base = getenv("ELFUSE_ABSOCK_BASE");
    if (custom_base) {
        char clean_base[64];
        if (absock_validate_custom_base(custom_base, clean_base, sizeof(clean_base)) < 0)
            return -1;

        int n = snprintf(out, out_sz, "%s/n%016llx",
                         clean_base, (unsigned long long) namespace_id);
        if (n < 0 || (size_t) n >= out_sz || (size_t) n > 72) {
            errno = ENAMETOOLONG;
            return -1;
        }
        return n;
    }

    return snprintf(out, out_sz, "/tmp/elfuse-absock-%llu",
                    (unsigned long long) namespace_id);
}

int main(void)
{
    char buf[128];
    int rc;

    printf("=== UNIT TESTS: absock_dir_format & absock_validate_custom_base ===\n");

    // 1. Unset env defaults to /tmp
    unsetenv("ELFUSE_ABSOCK_BASE");
    rc = absock_dir_format(buf, sizeof(buf), 12345);
    if (rc > 0 && strcmp(buf, "/tmp/elfuse-absock-12345") == 0) {
        printf("PASS: test_unset_defaults_to_tmp -> %s\n", buf);
    } else {
        printf("FAIL: test_unset_defaults_to_tmp rc=%d buf=%s\n", rc, buf);
        return 1;
    }

    // 2. Set empty env fails immediately without fallback
    setenv("ELFUSE_ABSOCK_BASE", "", 1);
    errno = 0;
    rc = absock_dir_format(buf, sizeof(buf), 12345);
    if (rc < 0 && errno == EINVAL) {
        printf("PASS: test_set_empty_fails_einval\n");
    } else {
        printf("FAIL: test_set_empty_fails_einval rc=%d errno=%d\n", rc, errno);
        return 2;
    }

    // 3. Relative path fails with EINVAL
    setenv("ELFUSE_ABSOCK_BASE", "relative/path", 1);
    errno = 0;
    rc = absock_dir_format(buf, sizeof(buf), 12345);
    if (rc < 0 && errno == EINVAL) {
        printf("PASS: test_relative_path_fails_einval\n");
    } else {
        printf("FAIL: test_relative_path_fails_einval rc=%d errno=%d\n", rc, errno);
        return 3;
    }

    // 4. Nonexistent directory (< 60 chars) fails with ENOENT
    const char *nonexistent_base = "/Users/mewcapoo/Projects/proton-macos-lab/.no_such_dir";
    setenv("ELFUSE_ABSOCK_BASE", nonexistent_base, 1);
    errno = 0;
    rc = absock_dir_format(buf, sizeof(buf), 12345);
    if (rc < 0 && errno == ENOENT) {
        printf("PASS: test_nonexistent_dir_fails_enoent\n");
    } else {
        printf("FAIL: test_nonexistent_dir_fails_enoent rc=%d errno=%d\n", rc, errno);
        return 4;
    }

    // 5. Valid 0700 base succeeds
    const char *valid_base = "/Users/mewcapoo/Projects/proton-macos-lab/.sr";
    setenv("ELFUSE_ABSOCK_BASE", valid_base, 1);
    errno = 0;
    rc = absock_dir_format(buf, sizeof(buf), 12345);
    if (rc > 0 && strstr(buf, "/.sr/n0000000000003039") != NULL) {
        printf("PASS: test_valid_0700_base_succeeds -> %s\n", buf);
    } else {
        printf("FAIL: test_valid_0700_base_succeeds rc=%d errno=%d buf=%s\n", rc, errno, buf);
        return 5;
    }

    // 6. Valid base with trailing slashes stripped and succeeds
    setenv("ELFUSE_ABSOCK_BASE", "/Users/mewcapoo/Projects/proton-macos-lab/.sr///", 1);
    errno = 0;
    rc = absock_dir_format(buf, sizeof(buf), 12345);
    if (rc > 0 && strstr(buf, "/.sr/n0000000000003039") != NULL) {
        printf("PASS: test_trailing_slashes_stripped_succeeds -> %s\n", buf);
    } else {
        printf("FAIL: test_trailing_slashes_stripped_succeeds rc=%d errno=%d buf=%s\n", rc, errno, buf);
        return 6;
    }

    // 7. Symlink base (< 60 chars) fails with ELOOP (even with trailing slash)
    const char *symlink_path = "/Users/mewcapoo/Projects/proton-macos-lab/.sr_lnk";
    unlink(symlink_path);
    symlink(valid_base, symlink_path);

    setenv("ELFUSE_ABSOCK_BASE", symlink_path, 1);
    errno = 0;
    rc = absock_dir_format(buf, sizeof(buf), 12345);
    if (rc < 0 && errno == ELOOP) {
        printf("PASS: test_symlink_base_fails_eloop\n");
    } else {
        printf("FAIL: test_symlink_base_fails_eloop rc=%d errno=%d\n", rc, errno);
        unlink(symlink_path);
        return 7;
    }

    // 7b. Symlink with trailing slash must also fail with ELOOP
    char symlink_slash[256];
    snprintf(symlink_slash, sizeof(symlink_slash), "%s/", symlink_path);
    setenv("ELFUSE_ABSOCK_BASE", symlink_slash, 1);
    errno = 0;
    rc = absock_dir_format(buf, sizeof(buf), 12345);
    if (rc < 0 && errno == ELOOP) {
        printf("PASS: test_symlink_trailing_slash_fails_eloop\n");
    } else {
        printf("FAIL: test_symlink_trailing_slash_fails_eloop rc=%d errno=%d\n", rc, errno);
        unlink(symlink_path);
        return 8;
    }
    unlink(symlink_path);

    // 8. Group/other readable or world-writable directory fails with EACCES
    const char *bad_perm_dir = "/Users/mewcapoo/Projects/proton-macos-lab/.sr_bad_perm";
    mkdir(bad_perm_dir, 0755);
    setenv("ELFUSE_ABSOCK_BASE", bad_perm_dir, 1);
    errno = 0;
    rc = absock_dir_format(buf, sizeof(buf), 12345);
    if (rc < 0 && errno == EACCES) {
        printf("PASS: test_bad_permission_fails_eacces\n");
    } else {
        printf("FAIL: test_bad_permission_fails_eacces rc=%d errno=%d\n", rc, errno);
        rmdir(bad_perm_dir);
        return 9;
    }
    rmdir(bad_perm_dir);

    // 9. Base path >= 60 bytes fails with ENAMETOOLONG
    const char *too_long_base = "/Users/mewcapoo/Projects/proton-macos-lab/123456789012345678901234567890";
    setenv("ELFUSE_ABSOCK_BASE", too_long_base, 1);
    errno = 0;
    rc = absock_dir_format(buf, sizeof(buf), 12345);
    if (rc < 0 && errno == ENAMETOOLONG) {
        printf("PASS: test_too_long_base_fails_enametoolong\n");
    } else {
        printf("FAIL: test_too_long_base_fails_enametoolong rc=%d errno=%d\n", rc, errno);
        return 10;
    }

    printf("ALL 10 UNIT TESTS PASSED SUCCESSFULLY!\n");
    return 0;
}
