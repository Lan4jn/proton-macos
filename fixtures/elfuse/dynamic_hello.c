#include <unistd.h>

int main(void) {
    const char msg[] = "Dynamic glibc hello under elfuse\n";
    write(1, msg, sizeof(msg) - 1);
    return 0;
}
