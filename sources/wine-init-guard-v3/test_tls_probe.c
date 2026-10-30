#include <stdint.h>

static __thread uint32_t vulkan_init_depth = 0;

void vulkan_init_guard_enter(void) {
    vulkan_init_depth++;
}

void vulkan_init_guard_exit(void) {
    if (vulkan_init_depth > 0) vulkan_init_depth--;
}

int is_vulkan_init_in_progress(void) {
    return vulkan_init_depth > 0;
}
