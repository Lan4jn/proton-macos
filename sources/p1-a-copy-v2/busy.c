#include <stdint.h>
#include <mach/mach_time.h>

/* Host producer only: no IPC, sleep, event pump or guest runtime in this loop. */
uint64_t busy_ns(uint64_t duration) {
    mach_timebase_info_data_t tb; mach_timebase_info(&tb);
    uint64_t begin=mach_absolute_time();
    uint64_t ticks=(uint64_t)((__uint128_t)duration*tb.denom/tb.numer);
    volatile uint64_t accumulator=1;
    uint64_t operations=0;
    do {
        for(unsigned i=0;i<100000;i++) {
            accumulator=accumulator*6364136223846793005ULL+1442695040888963407ULL;
            operations++;
        }
    } while(mach_absolute_time()-begin<ticks);
    return operations+(accumulator==0);
}
