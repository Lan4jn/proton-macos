#include <unistd.h>
#include <string.h>
#include <stdlib.h>

int main(int argc, char **argv) {
    char *new_argv[argc + 2];
    int has_f = 0;
    int idx = 0;

    new_argv[idx++] = "/wine/bin-arm64/wineserver";

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "-f") == 0 || strcmp(argv[i], "--foreground") == 0) {
            has_f = 1;
        }
        new_argv[idx++] = argv[i];
    }

    if (!has_f) {
        new_argv[idx++] = "-f";
    }
    new_argv[idx] = NULL;

    execv("/wine/bin-arm64/wineserver", new_argv);
    return 127;
}
