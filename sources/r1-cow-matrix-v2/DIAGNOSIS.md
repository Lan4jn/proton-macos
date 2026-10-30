# R1 first-round mechanism diagnostic

## Initial host-only snapshot (superseded by authorized guest addendum)

- **Host POSIX only:** host page size 16384; 4096-byte lane cases: 6 PASS, 3 UNSUPPORTED_ALIGNMENT (fixed/protect/remap, exit77). Native 16384-byte lane cases: 9 PASS. No timeouts observed; per-case budget 8 seconds. This is not a guest COW pass.
- **Real guest:** NOT_RUN / P0_REVIEW_PENDING. A genuine static aarch64 Linux ELF was built using already-installed Zig; it was not launched. Guest page size remains unobserved, expected 4096 must be checked from probe JSON at execution.
- **Windows WRITECOPY:** NOT_TESTED. MAP_PRIVATE is a mechanism proxy only.

Evidence: [host receipt](../../logs/r1-cow-matrix-v2/20261028T103508-ed529158/receipt.json), [build/test commands and hashes](../../logs/r1-cow-matrix-v2/20261028T103508-ed529158/verification.json). Host receipt has actual commands, cwd, stdout/stderr paths and SHA, target exits, timeout flags and independent file/sibling/neighbor assertions. Build and tests exited 0; unittest reports 6 tests OK. The initial red run failed `probe must be built` before C implementation existed (tool output; no persisted initial-red log).

## Authorized guest results — final addendum

After the initial host-only report, Lead approved C3b guest execution, then revised scheduling to original8180. The original C group completed before the revised message was delivered; it remains recorded rather than relabeled. Review then exposed missing child-store evidence. Lead approved exactly one enhanced original group plus one C fork-private supplement; all runs are now frozen.

| Runtime / ELF | Coverage | Measured result |
|---|---|---|
| Original 8180332221745ee0a1870d1bf588ce97cb72fa1dc9a7e8f0c89af918ff0abcda / enhanced ELF 93dc86f9bb2bf568c1c140c883bf738ab4359cd97610a12485ac7c7b7f95046b | nine 4096-lane cases | seven PASS; fixed and remap FAIL, target exit1 |
| Derived 3b146bbe872aaff1554fe887f419539b8f32747062b66c1afb7f96c661cab926 / old ELF 03615d3eec448718a4b971b26850c7de3076331a4327f5f12f88cd8b35137556 | nine 4096-lane cases | six valid PASS, two FAIL; fork-private raw PASS is EVIDENCE_INCOMPLETE |
| Derived 3b146bbe872aaff1554fe887f419539b8f32747062b66c1afb7f96c661cab926 / enhanced ELF 93dc86f9bb2bf568c1c140c883bf738ab4359cd97610a12485ac7c7b7f95046b | fork-private only | PASS; child readback85, parent17, file17, private sibling17 |

All guest JSON reports actual page_size4096. All session receipts show both supervisor timeouts false and cleanup.complete true. Runtime watchdog5s, supervisor20s, outer30s are distinct budgets; watchdog did not fire. Successful case target/runner exits0; semantic FAIL target/runner exits1. The orchestration script itself exited0 because recording semantic failures is its purpose, not a matrix pass.

Original and derived fixed/remap have matching observed symptoms: neighbor byte0 instead of119, file=false, sibling=true, neighbor=false. Target remains85 (fixed) /102 (remap); backing target is17 /85 as expected. **file=false combines full-file and shared-alias checks; current raw output does not identify the first differing byte or distinguish the two checks. It does not independently prove disk corruption.** Both runtimes losing neighbor visibility supports narrowing the next design to mixed-granule overlay lifecycle, not a C-present-only regression. This is not a demonstrated production fix or full root-cause proof.

Frozen guest evidence: [initial derived receipt](../../logs/r1-cow-matrix-v2/guest-20261028T104804-faf7bb/receipt.json), [original plus supplement receipt](../../logs/r1-cow-matrix-v2/review-guest-20261028T105722-8bcfbf/receipt.json). Each contains exact commands, runtime/ELF SHA, isolated root and session-receipt SHA; linked session directories contain stdout/stderr, config, owned-process/cleanup events. Old ELF copies remain in old fixture roots; no historical receipt was edited.

Review enhancement: child writes through volatile pointer, sends its own readback through a pipe, and parent fails when readback differs from85. Test-first red observed `None != 85`; after implementation 8 unittest tests OK. Mutation removing the child store yields exit1/readback17/sibling=false. This repairs an observation gap, not runtime behavior. New fixture does not retroactively validate the old fork-private result.

The earlier NOT_RUN/P0_PENDING text below describes the report's initial snapshot only; the addendum and linked guest receipts are the final state. No more guest rounds are scheduled.

## Reproduction

```sh
clang -std=c11 -Wall -Wextra -Werror -pthread sources/r1-cow-matrix-v2/probe.c -o sources/r1-cow-matrix-v2/probe-host
zig cc -target aarch64-linux-musl -static -std=c11 -Wall -Wextra -Werror -pthread -fno-sanitize=all sources/r1-cow-matrix-v2/probe.c -o sources/r1-cow-matrix-v2/probe-linux-aarch64
python3 -I -m unittest discover -s tests/r1_cow_matrix_v2 -v
python3 -I scripts/r1_cow_matrix_v2/capture_host.py
```

Each capture creates a unique new directory, no overwrite/deletion of historical logs. Backing files are freshly mkstemp-created in the run cwd and immediately unlinked by owning probe. gate is removed from child environment; probe rejects any explicit value, including `0`. File checks scan full mapping; neighbor checks scan all bytes outside target lane; sibling target is first dirtied to isolate it from implementation-defined untouched-private/file-update visibility. pthread_join/waitpid provide deterministic boundaries, not concurrent-race stress.

## Static diagnosis: narrow candidate boundary, not a demonstrated repair

Read-only inspected [derived mem.c](../elfuse-inproc-present-derived/src/syscall/mem.c):

1. Lines 3528–3595: host-aligned writable SHARED gets file overlay; PRIVATE and misaligned SHARED fall through to pread snapshot. Thus host-aligned SHARED and a guest 4K-misaligned SHARED map use materially different backing mechanisms. This is a source-supported hypothesis for visibility differences, not a fresh guest observation.
2. Lines 2491–2495: cleanup expands guest requested range to host-page boundaries. Lines 3191–3233 replace MAP_FIXED mappings with overlays or snapshots. A 4K private replacement inside a 16K shared backing needs preservation of the other three 4K lanes' backing identity and shared-update visibility, not just copying their current bytes.
3. Lines 2091–2106 describe HVF segment unmap/remap needed to refresh host VA mapping, and lines 2162–2165 require sibling-vCPU quiescence. Comments are implementation intent; no fresh HVF experiment was run here.

**Minimum plausible repair seam:** overlay/backing lifecycle bookkeeping at host16K granules with per-guest4K lane identity, transactional replacement/restoration, and preservation/reinstallation of neighboring shared lanes across fixed/unmap/remap and fork. Scope includes region metadata plus HVF remap/quiescence integration. A simple Stage-2 read-only+copy approach is not proven to satisfy shared neighbors, fork inheritance, or teardown. Exact design and cost remain undecided pending actual guest failures and Wine semantic probes.

**Historical premise correction:** old private-cow-decision.md treats post-mmap external-file writes to untouched MAP_PRIVATE as a universal mandatory POSIX promise and claims an architecture-level impossibility. This probe deliberately does not encode that claim. File/sibling isolation and explicit SHARED visibility are asserted; private external-file visibility requires a separately stated Linux/Wine requirement and primary documentation/runtime evidence. No historical report was modified.

## Unmeasured and limitations

- mprotect tests RO→RW calls and post-transition data, not write-while-RO SIGSEGV enforcement.
- `lanes` is full-byte neighbor preservation with one target write, not exhaustive independent four-lane write combinations.
- unmap/remap immediately reconstructs mapping; accesses while unmapped and concurrent teardown are not tested.
- Fork is synchronized parent/child, not race stress or exec; thread test uses join.
- No Windows section/WRITECOPY API, mremap, protection faults, EOF/SIGBUS, readonly-fd errors, signal/futex regressions, or production fixes. Guest coverage is only the explicitly listed cases above.
- Host capture uses subprocess timeout for the probe leader; it is not the P0 process-tree ownership runner. Current probe children do one store then immediate _exit. Future guest runs must use reviewed session_v2 rather than this host-only script.
- No git metadata exists at workspace root (`git status` exited128), so no git-diff provenance claim. Changes are confined to task-5 paths by operation history; runtime/Wine and existing evidence were read-only. No commit/push, real Steam, system or global package changes.

## Guest integration checkpoint

session-worker proposed CLI `python3 -I scripts/runtime/session_v2/run.py --run-id ID --timeout SECONDS --outer-timeout SECONDS --module ROLE=PATH [--env KEY=VALUE] -- COMMAND ARG...`, fixed logs/session-v2 root. This interface is provisional and requires P0 review. Actual runtime root mounting/fixture path translation is not yet agreed. After approval, issue nine separate 4096-lane commands, record guest `_SC_PAGESIZE`, assert gate absent, bind runtime+ELF SHA and runner receipt. Never replace NOT_RUN with host results.
