# HVF Read-Only Host Mapping Probe Report
- Evidence: logs/hvf-readonly-probe/probe.jsonl, logs/hvf-readonly-probe/probe.log
- Test count: 11 unit tests passed; 1 live probe execution (4 cases evaluated).
- Artifacts: Source SHA eb7cd40a0a1e..., Binary SHA 3694ff312e47..., Seed SHA matched (1fde717d808c...).
- VM Lifecycle: hv_vm_create=OK, hv_vm_destroy=OK.
- Cases: A(anon RWX)=0x00000000, B(file RO->HV_R)=0xfae94001, C(file RO->HV_RWX)=0xfae94001, D(file RW->HV_RWX)=0x00000000.
- Admission Verdict: REJECTED (RO_HOST_MAPPING_REJECTED (hv_return=0xfae94001)).
- Controls: Positive controls A & D succeeded; no silent retry or Blind Reuse performed.
- Unmeasured Scope: vCPU execution, guest address translation coherence, Wine/Proton runtime memory patching.
