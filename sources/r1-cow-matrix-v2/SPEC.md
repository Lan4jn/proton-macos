# R1 task-5 specification / plan

Lead approved nine cases and native-page controls via team message. Only new task-5 scopes are writable. No commits, production changes or guest execution before P0 review.

Portable C probe, one case per invocation: shared, private, lanes, fixed, protect, thread, fork-private, fork-shared, remap. JSON includes page size, requested lane, file/sibling/neighbor observations and independent assertions. Exit 0: assertions passed; 1: semantic failure; 2: setup/syscall error; 77: unsupported alignment. MAP_PRIVATE is only a WRITECOPY mechanism proxy, not Windows WRITECOPY coverage. Host results never stand in for guest.

1. Write integration tests first: build required, nine native cases emit independent assertions, subpage operations explicitly unsupported, opt-in rejected, invalid case rejected. Run red.
2. Implement minimal C with fresh temporary backing, pthread join/fork wait synchronization and external per-case timeout.
3. Compile host clang -Wall -Wextra -Werror -pthread. Build Linux ELF only with existing compiler/sysroot; no installs.
4. Run 4096 and host-page lanes into unique logs, preserve commands/stdout/stderr/exit/timeouts/SHA. Guest NOT_RUN/P0_PENDING.
5. Read current runtime boundaries; report candidate seams as hypotheses, not fixes. Independent reviewer validates.

Not covered: runtime/Wine repair, Windows WRITECOPY, arbitrary fork races, mremap, huge pages, signals/futex regressions, full cross-product. External-file-update visibility in MAP_PRIVATE is observation, not a universal POSIX assertion. Same hypothesis limited to two rounds.
