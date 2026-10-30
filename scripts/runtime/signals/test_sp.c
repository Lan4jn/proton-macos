#include <stdio.h>
#include <stdint.h>

static void *get_sp_asm(void) {
    void *sp;
    asm volatile("mov %0, sp" : "=r"(sp));
    return sp;
}

int main(void) {
    void *sp = get_sp_asm();
    printf("ARM64 SP=%p (uintptr: 0x%lx)\n", sp, (uintptr_t)sp);
    return 0;
}
