/*
 * fixtures/runtime/badalloc-phase/test_pure_c.c
 *
 * Case 1: Pure C executable. Only links libc.
 * Contains no C++ code or libraries.
 * Verifies that constructor runs, non-fatal resolution handles absent C++ runtime,
 * and program exits cleanly with code 0.
 */

#include <stdio.h>

int main(void)
{
    printf("CASE1_PURE_C_OK\n");
    return 0;
}
