# P1 A-copy v2 — approved frame/ACK v1

Lead approved A1 and the contract on 2026-10-28. Scope: host-only CPU producer + independent AppKit process; not Wine/GDI. P0 approval gates guest execution. No P2. Original runtime/Wine/historical evidence read-only.

## Alternatives
A1 chosen: AF_UNIX SOCK_STREAM actual RGBA8 copy, Python stdlib producer and Objective-C AppKit host. A2 shared memory adds pinning/lifetime complexity. A3 cooperative UI fails syscall-free computation response.

## Wire
u32be total length, u32be JSON length, UTF-8 JSON, payload. Total includes JSON length word, JSON and payload; excludes outer word. Validate 4<=total<=16777216 before allocation; JSON length<=total-4. v=1, sid=1; gen/seq positive integers <=2^63-1; seq strictly increases across generations. w/h 1..4096, pitch=w*4, format=RGBA8, payload_bytes=pitch*h. No guest addresses.

CREATE starts gen=1. RESIZE strictly increases gen. Both carry shape; host main-thread barrier drains old READING and invalidates old READY before ACK ack_for=CREATE|RESIZE stage=CONFIGURED. FRAME requires current shape, gen, seq, crc32/payload_bytes. Full shape/CRC validation before RECEIVED; invalid protocol ERROR then bounded close, no partial display.

FRAME ACK ack_for=FRAME stage=RECEIVED sid/gen/seq/slot/crc32 means full copy into host-owned READY, not display. Host assigns slot 0/1. FREE→WRITING→READY→READING→FREE; never overwrite READING. At most one READY; new READY replaces old READY. Every RECEIVED has exactly one CONSUMED terminal disposition=displayed|replaced|invalidated; host slot released. Only displayed counts draw success. Correctness producer waits terminal each frame. All replacements logged. Partial frames not RECEIVED do not count as success.

CLOSE ACK ack_for=CLOSE stage=CLOSED then stop. EOF or peer exit releases slots and exits <=3s. Negative cases: oversize length, short reads/truncation, shape overflow, stale gen, duplicate seq, CRC. Host receive→consume age and producer same-clock RTT separate; cross-process one-way UNKNOWN.

## Approved public seams and validation
1. OwnedSession/new_run: unique directory refusal, owned Popen PID/group TERM→bounded KILL, sentinel survival.
2. Real AF_UNIX wire→ACK/ERROR, limits and stale identities.
3. Real AppKit NSView draw + bitmap capture: pixel comparison domain opaque RGBA8 DeviceRGB; alpha always255, format conversion recorded. Not desktop compositor/unoccluded output proof.
4. Producer CLI→receipts: 1000 changing frames; 30s1280x72030 distributions/queue/replacements; faster producer latest-frame-wins; producer native 3s busy with host events prearranged before busy; independent close run. At most two rounds per hypothesis.

## Scope/evidence
Only sources/p1-a-copy-v2, scripts/p1_a_copy_v2, tests/p1_a_copy_v2, logs/p1-a-copy-v2. Unique run dirs, existing refused. Receipts bind argv/PID/PGID/target+runner exits/inner+outer timeouts/cleanup/SHA256/limits. No global install, killall, commit/push, Steam/system changes.
