#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <signal.h>
#include <string.h>
#include <errno.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <sys/time.h>
#include <stdint.h>

#define TEST_PASS 0
#define TEST_FAIL 1

static volatile sig_atomic_t g_got_sig = 0;
static volatile sig_atomic_t g_handler_errno = 0;
static volatile siginfo_t g_siginfo_copy;
static volatile void *g_handler_sp = NULL;
static volatile sigset_t g_handler_mask;

static void *get_sp(void) {
    void *sp;
    asm volatile("mov %0, sp" : "=r"(sp));
    return sp;
}

/* --------------------------------------------------------------------------
 * Subtest 1: Basic Delivery & errno / sa_mask preservation
 * -------------------------------------------------------------------------- */
static void handler_basic(int sig) {
    g_got_sig = sig;
    g_handler_errno = errno;
    errno = 99; /* Mutate errno inside handler */
    sigprocmask(SIG_SETMASK, NULL, (sigset_t *)&g_handler_mask);
}

static int run_test_1_basic(void) {
    printf("\n=== Test 1: Basic Delivery & errno / sa_mask ===\n");
    g_got_sig = 0;
    g_handler_errno = 0;

    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = handler_basic;
    sigemptyset(&sa.sa_mask);
    sigaddset(&sa.sa_mask, SIGUSR2); /* Mask SIGUSR2 during SIGUSR1 */

    if (sigaction(SIGUSR1, &sa, NULL) != 0) {
        printf("[TEST 1 FAIL] sigaction failed: %s\n", strerror(errno));
        return TEST_FAIL;
    }

    errno = 42; /* Known outer errno */
    if (raise(SIGUSR1) != 0) {
        printf("[TEST 1 FAIL] raise failed: %s\n", strerror(errno));
        return TEST_FAIL;
    }

    if (g_got_sig != SIGUSR1) {
        printf("[TEST 1 FAIL] Handler not triggered: g_got_sig=%d (expected %d)\n", g_got_sig, SIGUSR1);
        return TEST_FAIL;
    }
    if (g_handler_errno != 42) {
        printf("[TEST 1 FAIL] Handler did not observe outer errno: %d (expected 42)\n", g_handler_errno);
        return TEST_FAIL;
    }
    if (!sigismember((sigset_t *)&g_handler_mask, SIGUSR2)) {
        printf("[TEST 1 FAIL] sa_mask SIGUSR2 not active inside handler\n");
        return TEST_FAIL;
    }

    /* Note: In standard Linux/C runtime, errno is thread-local __thread int.
     * When a signal handler runs on the same thread, any mutation to errno
     * persists unless user code explicitly saves/restores it.
     * Test whether user errno mutation persists as expected in C library:
     */
    printf("[TEST 1 INFO] Handler observed outer errno=%d, outer errno after handler=%d\n", g_handler_errno, errno);
    printf("[TEST 1 PASS] Basic signal delivery and sa_mask verified\n");
    return TEST_PASS;
}

/* --------------------------------------------------------------------------
 * Subtest 2: sigaction SA_RESTART vs EINTR on blocking syscall
 * -------------------------------------------------------------------------- */
static void handler_dummy(int sig) {
    g_got_sig = sig;
}

static int run_test_2_restart(void) {
    printf("\n=== Test 2: SA_RESTART vs EINTR on blocking read ===\n");
    int pipefd[2];
    if (pipe(pipefd) != 0) {
        printf("[TEST 2 FAIL] pipe creation failed: %s\n", strerror(errno));
        return TEST_FAIL;
    }

    /* Part 2a: Without SA_RESTART -> read() should return -1 with EINTR */
    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = handler_dummy;
    sigemptyset(&sa.sa_mask);
    sa.sa_flags = 0; /* NO SA_RESTART */

    if (sigaction(SIGALRM, &sa, NULL) != 0) {
        printf("[TEST 2a FAIL] sigaction failed: %s\n", strerror(errno));
        close(pipefd[0]); close(pipefd[1]);
        return TEST_FAIL;
    }

    g_got_sig = 0;
    ualarm(50000, 0); /* 50ms alarm */
    char buf[16];
    ssize_t nr = read(pipefd[0], buf, sizeof(buf));
    int err = errno;
    ualarm(0, 0);

    if (nr != -1 || err != EINTR) {
        printf("[TEST 2a FAIL] Blocking read without SA_RESTART did not return EINTR: nr=%zd err=%d (%s)\n",
               nr, err, strerror(err));
        close(pipefd[0]); close(pipefd[1]);
        return TEST_FAIL;
    }
    printf("[TEST 2a PASS] Blocking read returned EINTR without SA_RESTART (g_got_sig=%d)\n", g_got_sig);

    /* Part 2b: With SA_RESTART -> fork child that writes after delay, read() should restart and succeed */
    sa.sa_flags = SA_RESTART;
    if (sigaction(SIGALRM, &sa, NULL) != 0) {
        printf("[TEST 2b FAIL] sigaction failed: %s\n", strerror(errno));
        close(pipefd[0]); close(pipefd[1]);
        return TEST_FAIL;
    }

    g_got_sig = 0;
    pid_t pid = fork();
    if (pid == 0) {
        /* Child */
        close(pipefd[0]);
        usleep(80000); /* 80ms delay */
        write(pipefd[1], "OK", 2);
        close(pipefd[1]);
        _exit(0);
    }

    close(pipefd[1]);
    ualarm(30000, 0); /* 30ms alarm, fires before child writes */
    memset(buf, 0, sizeof(buf));
    nr = read(pipefd[0], buf, 2);
    err = errno;
    ualarm(0, 0);
    int status = 0;
    waitpid(pid, &status, 0);
    close(pipefd[0]);

    if (g_got_sig != SIGALRM) {
        printf("[TEST 2b FAIL] SIGALRM was not delivered: g_got_sig=%d\n", g_got_sig);
        return TEST_FAIL;
    }
    if (nr != 2 || memcmp(buf, "OK", 2) != 0) {
        printf("[TEST 2b FAIL] SA_RESTART read did not restart: nr=%zd err=%d (%s) buf='%s'\n",
               nr, err, strerror(err), buf);
        return TEST_FAIL;
    }

    printf("[TEST 2b PASS] Blocking read successfully restarted with SA_RESTART and read data\n");
    return TEST_PASS;
}

/* --------------------------------------------------------------------------
 * Subtest 3: SA_SIGINFO Passing siginfo_t
 * -------------------------------------------------------------------------- */
static void handler_siginfo(int sig, siginfo_t *info, void *ucontext) {
    g_got_sig = sig;
    if (info) {
        memcpy((void *)&g_siginfo_copy, info, sizeof(siginfo_t));
    }
}

static int run_test_3_siginfo(void) {
    printf("\n=== Test 3: SA_SIGINFO siginfo_t Validation ===\n");
    g_got_sig = 0;
    memset((void *)&g_siginfo_copy, 0, sizeof(siginfo_t));

    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_sigaction = handler_siginfo;
    sigemptyset(&sa.sa_mask);
    sa.sa_flags = SA_SIGINFO;

    if (sigaction(SIGUSR1, &sa, NULL) != 0) {
        printf("[TEST 3 FAIL] sigaction failed: %s\n", strerror(errno));
        return TEST_FAIL;
    }

    pid_t my_pid = getpid();
    if (kill(my_pid, SIGUSR1) != 0) {
        printf("[TEST 3 FAIL] kill failed: %s\n", strerror(errno));
        return TEST_FAIL;
    }

    if (g_got_sig != SIGUSR1) {
        printf("[TEST 3 FAIL] Signal not delivered: %d\n", g_got_sig);
        return TEST_FAIL;
    }
    if (g_siginfo_copy.si_signo != SIGUSR1) {
        printf("[TEST 3 FAIL] si_signo mismatch: got %d (expected %d)\n", g_siginfo_copy.si_signo, SIGUSR1);
        return TEST_FAIL;
    }
    if (g_siginfo_copy.si_pid != my_pid) {
        printf("[TEST 3 FAIL] si_pid mismatch: got %d (expected %d)\n", g_siginfo_copy.si_pid, my_pid);
        return TEST_FAIL;
    }
    if (g_siginfo_copy.si_code != SI_USER && g_siginfo_copy.si_code != SI_TKILL) {
        printf("[TEST 3 FAIL] si_code mismatch: got %d (expected SI_USER=0 or SI_TKILL=-6)\n", g_siginfo_copy.si_code);
        return TEST_FAIL;
    }

    printf("[TEST 3 PASS] SA_SIGINFO correctly delivered (si_signo=%d, si_pid=%d, si_code=%d)\n",
           g_siginfo_copy.si_signo, g_siginfo_copy.si_pid, g_siginfo_copy.si_code);
    return TEST_PASS;
}

/* --------------------------------------------------------------------------
 * Subtest 4: sigaltstack Alternate Signal Stack
 * -------------------------------------------------------------------------- */
static void handler_altstack(int sig) {
    g_got_sig = sig;
    g_handler_sp = get_sp();
}

static int run_test_4_altstack(void) {
    printf("\n=== Test 4: sigaltstack Execution ===\n");
    g_got_sig = 0;
    g_handler_sp = NULL;

    size_t stack_sz = 64 * 1024;
    void *alt_mem = malloc(stack_sz);
    if (!alt_mem) {
        printf("[TEST 4 FAIL] malloc altstack failed\n");
        return TEST_FAIL;
    }

    stack_t ss;
    ss.ss_sp = alt_mem;
    ss.ss_size = stack_sz;
    ss.ss_flags = 0;

    if (sigaltstack(&ss, NULL) != 0) {
        printf("[TEST 4 FAIL] sigaltstack failed: %s\n", strerror(errno));
        free(alt_mem);
        return TEST_FAIL;
    }

    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = handler_altstack;
    sigemptyset(&sa.sa_mask);
    sa.sa_flags = SA_ONSTACK;

    if (sigaction(SIGUSR2, &sa, NULL) != 0) {
        printf("[TEST 4 FAIL] sigaction SA_ONSTACK failed: %s\n", strerror(errno));
        free(alt_mem);
        return TEST_FAIL;
    }

    raise(SIGUSR2);

    uintptr_t sp_val = (uintptr_t)g_handler_sp;
    uintptr_t alt_start = (uintptr_t)alt_mem;
    uintptr_t alt_end = alt_start + stack_sz;

    int pass = (g_got_sig == SIGUSR2) && (sp_val >= alt_start && sp_val < alt_end);
    if (!pass) {
        printf("[TEST 4 FAIL] Handler SP %p not within altstack [%p, %p)\n",
               g_handler_sp, (void *)alt_start, (void *)alt_end);
        free(alt_mem);
        return TEST_FAIL;
    }

    /* Disable altstack */
    ss.ss_flags = SS_DISABLE;
    sigaltstack(&ss, NULL);
    free(alt_mem);

    printf("[TEST 4 PASS] Handler ran on altstack: SP=%p in [%p, %p)\n",
           g_handler_sp, (void *)alt_start, (void *)alt_end);
    return TEST_PASS;
}

/* --------------------------------------------------------------------------
 * Subtest 5: sigprocmask Blocking & Pending Delivery
 * -------------------------------------------------------------------------- */
static int run_test_5_procmask(void) {
    printf("\n=== Test 5: sigprocmask Blocking & Pending Delivery ===\n");
    g_got_sig = 0;

    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = handler_dummy;
    sigemptyset(&sa.sa_mask);
    sigaction(SIGUSR1, &sa, NULL);

    /* Block SIGUSR1 */
    sigset_t set, oldset;
    sigemptyset(&set);
    sigaddset(&set, SIGUSR1);
    if (sigprocmask(SIG_BLOCK, &set, &oldset) != 0) {
        printf("[TEST 5 FAIL] sigprocmask SIG_BLOCK failed: %s\n", strerror(errno));
        return TEST_FAIL;
    }

    /* Raise blocked signal */
    raise(SIGUSR1);

    if (g_got_sig != 0) {
        printf("[TEST 5 FAIL] Signal delivered while blocked! g_got_sig=%d\n", g_got_sig);
        return TEST_FAIL;
    }

    /* Verify pending */
    sigset_t pending;
    sigemptyset(&pending);
    sigpending(&pending);
    if (!sigismember(&pending, SIGUSR1)) {
        printf("[TEST 5 FAIL] SIGUSR1 not reported in sigpending\n");
        return TEST_FAIL;
    }

    /* Unblock SIGUSR1 -> should deliver immediately */
    if (sigprocmask(SIG_UNBLOCK, &set, NULL) != 0) {
        printf("[TEST 5 FAIL] sigprocmask SIG_UNBLOCK failed: %s\n", strerror(errno));
        return TEST_FAIL;
    }

    if (g_got_sig != SIGUSR1) {
        printf("[TEST 5 FAIL] Signal not delivered upon unblock: g_got_sig=%d\n", g_got_sig);
        return TEST_FAIL;
    }

    printf("[TEST 5 PASS] Signal held while blocked and delivered immediately upon unblock\n");
    return TEST_PASS;
}

/* --------------------------------------------------------------------------
 * Subtest 6: SIGCHLD & waitpid Interaction
 * -------------------------------------------------------------------------- */
static void handler_chld(int sig, siginfo_t *info, void *ctx) {
    g_got_sig = sig;
    if (info) {
        memcpy((void *)&g_siginfo_copy, info, sizeof(siginfo_t));
    }
}

static int run_test_6_sigchld(void) {
    printf("\n=== Test 6: SIGCHLD & waitpid Interaction ===\n");
    g_got_sig = 0;
    memset((void *)&g_siginfo_copy, 0, sizeof(siginfo_t));

    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_sigaction = handler_chld;
    sigemptyset(&sa.sa_mask);
    sa.sa_flags = SA_SIGINFO;

    if (sigaction(SIGCHLD, &sa, NULL) != 0) {
        printf("[TEST 6 FAIL] sigaction SIGCHLD failed: %s\n", strerror(errno));
        return TEST_FAIL;
    }

    pid_t pid = fork();
    if (pid == 0) {
        usleep(30000); /* 30ms */
        _exit(42);
    }

    int status = 0;
    pid_t wpid = waitpid(pid, &status, 0);
    if (wpid != pid) {
        printf("[TEST 6 FAIL] waitpid failed: wpid=%d err=%s\n", wpid, strerror(errno));
        return TEST_FAIL;
    }

    if (!WIFEXITED(status) || WEXITSTATUS(status) != 42) {
        printf("[TEST 6 FAIL] Child status unexpected: %d\n", status);
        return TEST_FAIL;
    }

    /* Wait briefly for SIGCHLD delivery */
    for (int i = 0; i < 10 && g_got_sig == 0; i++) {
        usleep(10000);
    }

    if (g_got_sig != SIGCHLD) {
        printf("[TEST 6 FAIL] SIGCHLD not received on child exit: g_got_sig=%d\n", g_got_sig);
        return TEST_FAIL;
    }
    if (g_siginfo_copy.si_signo != SIGCHLD) {
        printf("[TEST 6 FAIL] SIGCHLD si_signo mismatch: %d\n", g_siginfo_copy.si_signo);
        return TEST_FAIL;
    }

    /* Check si_status: Linux kernel populates si_status with child exit code (42).
     * If elfuse synthetic siginfo zeroes si_status, report as failure/gap.
     */
    if (g_siginfo_copy.si_status != 42) {
        printf("[TEST 6 FAIL] SIGCHLD si_status not populated: got %d (expected 42)\n", g_siginfo_copy.si_status);
        return TEST_FAIL;
    }

    printf("[TEST 6 PASS] SIGCHLD received with si_status=42 and waitpid matched\n");
    return TEST_PASS;
}

/* --------------------------------------------------------------------------
 * Subtest 7: Timer Signals (setitimer & ITIMER_REAL)
 * -------------------------------------------------------------------------- */
static void handler_timer(int sig) {
    g_got_sig++;
}

static int run_test_7_timers(void) {
    printf("\n=== Test 7: Timer Signals (setitimer & ITIMER_REAL) ===\n");
    g_got_sig = 0;

    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = handler_timer;
    sigemptyset(&sa.sa_mask);
    sa.sa_flags = 0;

    if (sigaction(SIGALRM, &sa, NULL) != 0) {
        printf("[TEST 7 FAIL] sigaction SIGALRM failed: %s\n", strerror(errno));
        return TEST_FAIL;
    }

    struct itimerval itv;
    itv.it_interval.tv_sec = 0;
    itv.it_interval.tv_usec = 30000; /* 30ms repeat */
    itv.it_value.tv_sec = 0;
    itv.it_value.tv_usec = 30000;    /* 30ms first */

    if (setitimer(ITIMER_REAL, &itv, NULL) != 0) {
        printf("[TEST 7 FAIL] setitimer ITIMER_REAL failed: %s\n", strerror(errno));
        return TEST_FAIL;
    }

    /* Wait ~110ms: should get ~2-4 ticks */
    usleep(110000);

    /* Disarm */
    memset(&itv, 0, sizeof(itv));
    setitimer(ITIMER_REAL, &itv, NULL);

    if (g_got_sig < 2) {
        printf("[TEST 7 FAIL] setitimer ticks insufficient: got %d (expected >= 2)\n", g_got_sig);
        return TEST_FAIL;
    }

    printf("[TEST 7 PASS] setitimer ITIMER_REAL delivered %d timer ticks\n", g_got_sig);
    return TEST_PASS;
}

/* --------------------------------------------------------------------------
 * Main Driver
 * -------------------------------------------------------------------------- */
int main(int argc, char **argv) {
    int total_fail = 0;

    printf("STARTING GUEST SIGNAL SEMANTIC SUITE (ARM64 LINUX)\n");

    total_fail |= (run_test_1_basic() != 0)    ? (1 << 0) : 0;
    total_fail |= (run_test_2_restart() != 0)  ? (1 << 1) : 0;
    total_fail |= (run_test_3_siginfo() != 0)  ? (1 << 2) : 0;
    total_fail |= (run_test_4_altstack() != 0) ? (1 << 3) : 0;
    total_fail |= (run_test_5_procmask() != 0) ? (1 << 4) : 0;
    total_fail |= (run_test_6_sigchld() != 0)  ? (1 << 5) : 0;
    total_fail |= (run_test_7_timers() != 0)   ? (1 << 6) : 0;

    printf("\n=======================================================\n");
    if (total_fail == 0) {
        printf("ALL_7_SIGNAL_TESTS_PASS\n");
        return 0;
    } else {
        printf("SIGNAL_TESTS_FAILED failure_mask=0x%02x\n", total_fail);
        return total_fail;
    }
}
