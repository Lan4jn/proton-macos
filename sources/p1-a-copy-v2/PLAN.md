# A-copy implementation plan

Approved by Lead; inline execution as delegated worker, no delegation or git.

Files: sources/p1-a-copy-v2/{SPEC.md,PLAN.md,presenter.m,busy.c}; scripts/p1_a_copy_v2/{session.py,wire.py,run.py}; tests/p1_a_copy_v2/test_contract.py; logs/p1-a-copy-v2/<unique-run>/.

- [ ] Governance seam first: unittest unique directory refusal plus unrelated sentinel and owned sleeper cleanup. Run `python3 -m unittest discover -s tests/p1_a_copy_v2 -v`, see missing behavior; implement new_run and OwnedSession, rerun green.
- [ ] Wire seam: first test real socketpair fragmented packet roundtrip plus length/truncated rejection. See missing API; implement pack/read exact/validation. Rerun green.
- [ ] AppKit seam: black-box real process CREATE→FRAME→RECEIVED→CONSUMED, view CRC, and wrong identities ERROR. Run failure before presenter exists, then implement minimal Objective-C app with background socket reader and main-thread rendering.
- [ ] Throughput/lifetime seam: add runner scenarios for 1000 frames, 30s720p30, latest, resize, EOF and prearranged events/close during native CPU busy. Execute only after owned governance green. Record actual commands/exits, raw event logs, percentiles and SHA.
- [ ] Independent reviewer handoff; no P2, no guest execution before P0 release. Report any gaps rather than broadening claims. Each same hypothesis at most two rounds.
