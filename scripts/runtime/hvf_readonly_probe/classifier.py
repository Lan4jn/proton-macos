#!/usr/bin/env python3
"""
classifier.py - HVF Read-only Host Mapping Probe Output Classifier.

Classifies probe JSON/JSONL output according to strict verification rules:
1. Execution metadata binding:
   - Non-zero probe process return code -> INCONCLUSIVE
   - Process timeout -> INCONCLUSIVE
   - Backing seed SHA256 before != after mismatch -> INCONCLUSIVE
2. VM lifecycle & case integrity:
   - HVF VM creation failure or missing -> INCONCLUSIVE
   - Duplicate or missing cases (must be exactly unique A, B, C, D) -> INCONCLUSIVE
   - Missing or non-zero munmap/unmap -> CLEANUP_FAILURE (never assumed 0)
   - Map not executed or field None/malformed/conflicting -> INCONCLUSIVE (never fake REJECTED)
3. Positive controls:
   - Case A or Case D failure -> INCONCLUSIVE
4. Target evaluation:
   - Case B (O_RDONLY + PROT_READ + MAP_SHARED -> HV_MEMORY_READ) success -> ADMITTED
   - Case B failure with valid return code -> REJECTED
"""

import json
from typing import Any, Dict, List, Optional, Tuple, Union


HV_SUCCESS = 0


class ProbeClassifier:
    def __init__(self):
        pass

    def parse_input(self, text_or_obj: Any) -> Dict[str, Any]:
        """
        Parses raw text (JSON string, bytes, or JSONL) or pre-parsed dict.
        Returns a normalized dictionary structure.
        """
        if isinstance(text_or_obj, dict):
            return text_or_obj

        if isinstance(text_or_obj, bytes):
            text_or_obj = text_or_obj.decode("utf-8", errors="replace")

        if not isinstance(text_or_obj, str):
            raise ValueError(f"Unsupported input type: {type(text_or_obj)}")

        text = text_or_obj.strip()
        if not text:
            return {"vm_create": None, "cases": [], "vm_destroy": None}

        # Try parsing as single JSON object first
        if text.startswith("{") and text.endswith("}"):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict) and ("cases" in parsed or "vm_create" in parsed):
                    return parsed
            except json.JSONDecodeError:
                pass

        # Parse as JSONL lines
        events = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        # Reconstruct normalized structure from events
        vm_create = None
        cases = []
        vm_destroy = None
        summary = None

        for ev in events:
            if not isinstance(ev, dict):
                continue
            ev_type = ev.get("event")
            if ev_type == "vm_create":
                vm_create = ev
            elif ev_type == "case_result":
                cases.append(ev)
            elif ev_type == "vm_destroy":
                vm_destroy = ev
            elif ev_type == "summary":
                summary = ev
            elif "case_id" in ev and "hv_map_return" in ev:
                cases.append(ev)

        return {
            "vm_create": vm_create,
            "cases": cases,
            "vm_destroy": vm_destroy,
            "summary": summary,
        }

    def classify_execution(self, data, *, probe_returncode, timed_out,
                           seed_sha_before, seed_sha_after):
        """Issue an execution verdict only with complete, typed run evidence."""
        valid_hash = lambda value: (
            isinstance(value, str) and len(value) == 64
            and all(c in '0123456789abcdef' for c in value)
        )
        if (type(probe_returncode) is not int or type(timed_out) is not bool
                or not valid_hash(seed_sha_before) or not valid_hash(seed_sha_after)):
            return {'verdict': 'INCONCLUSIVE',
                    'reason': 'EXECUTION_EVIDENCE_MISSING_OR_INVALID', 'details': {}}
        return self.classify(data, probe_returncode=probe_returncode,
                             timed_out=timed_out, seed_sha_before=seed_sha_before,
                             seed_sha_after=seed_sha_after)


    def classify(
        self,
        data: Dict[str, Any],
        probe_returncode: Optional[int] = None,
        timed_out: Optional[bool] = None,
        seed_sha_before: Optional[str] = None,
        seed_sha_after: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Classifies probe results.
        Returns a dictionary with:
          - verdict: "ADMITTED" | "REJECTED" | "INCONCLUSIVE" | "CLEANUP_FAILURE"
          - reason: str
          - details: Dict[str, Any]
        """
        # 1. Top-level execution metadata binding
        if timed_out is True:
            return {
                "verdict": "INCONCLUSIVE",
                "reason": "EXECUTION_TIMED_OUT",
                "details": {"timed_out": True},
            }

        if probe_returncode is not None and probe_returncode != 0:
            return {
                "verdict": "INCONCLUSIVE",
                "reason": f"PROBE_PROCESS_FAILED (returncode={probe_returncode})",
                "details": {"returncode": probe_returncode},
            }

        if seed_sha_before is not None and seed_sha_after is not None:
            if seed_sha_before != seed_sha_after:
                return {
                    "verdict": "INCONCLUSIVE",
                    "reason": f"SEED_HASH_MISMATCH: before={seed_sha_before} after={seed_sha_after}",
                    "details": {
                        "seed_sha_before": seed_sha_before,
                        "seed_sha_after": seed_sha_after,
                    },
                }

        if not isinstance(data, dict):
            return {
                "verdict": "INCONCLUSIVE",
                "reason": "INVALID_DATA_FORMAT",
                "details": {"data": str(data)},
            }

        # 2. Check VM Lifecycle: vm_create
        vm_create = data.get("vm_create")
        if not isinstance(vm_create, dict):
            return {
                "verdict": "INCONCLUSIVE",
                "reason": "HVF_VM_CREATE_NOT_RECORDED",
                "details": {"vm_create": vm_create},
            }

        create_ret = vm_create.get("hv_return")
        create_success = vm_create.get("success")
        if not isinstance(create_ret, int) or not isinstance(create_success, bool):
            return {
                "verdict": "INCONCLUSIVE",
                "reason": "VM_CREATE_FIELD_INVALID",
                "details": {"vm_create": vm_create},
            }
        if (create_ret == HV_SUCCESS) != (create_success is True):
            return {
                "verdict": "INCONCLUSIVE",
                "reason": f"VM_CREATE_RESULT_CONFLICT (hv_return={create_ret}, success={create_success})",
                "details": {"vm_create": vm_create},
            }
        if create_ret != HV_SUCCESS:
            return {
                "verdict": "INCONCLUSIVE",
                "reason": f"HVF_VM_CREATE_FAILED (hv_return={create_ret:#x})",
                "details": {
                    "vm_create": vm_create,
                    "note": "Cannot determine R-only admission because VM creation failed",
                },
            }

        # 3. Check Cases Completeness & Uniqueness (exactly unique A, B, C, D)
        cases_list = data.get("cases")
        if not isinstance(cases_list, list):
            return {
                "verdict": "INCONCLUSIVE",
                "reason": "CASES_NOT_A_LIST",
                "details": {"cases": cases_list},
            }

        seen_case_ids = set()
        cases_by_id: Dict[str, Dict[str, Any]] = {}
        for c in cases_list:
            if not isinstance(c, dict):
                return {
                    "verdict": "INCONCLUSIVE",
                    "reason": "CASE_ITEM_NOT_A_DICT",
                    "details": {"case": str(c)},
                }
            cid = c.get("case_id")
            if not cid or not isinstance(cid, str):
                return {
                    "verdict": "INCONCLUSIVE",
                    "reason": "CASE_ID_MISSING_OR_INVALID",
                    "details": {"case": c},
                }
            if cid in seen_case_ids:
                return {
                    "verdict": "INCONCLUSIVE",
                    "reason": f"DUPLICATE_CASE_ID: duplicate case {cid}",
                    "details": {"duplicate_case_id": cid},
                }
            seen_case_ids.add(cid)
            cases_by_id[cid] = c

        required_cases = ["A", "B", "C", "D"]
        missing_cases = [cid for cid in required_cases if cid not in cases_by_id]
        if missing_cases:
            return {
                "verdict": "INCONCLUSIVE",
                "reason": f"MISSING_CASES: missing {missing_cases}",
                "details": {
                    "present_cases": list(cases_by_id.keys()),
                    "missing_cases": missing_cases,
                },
            }

        extra_cases = [cid for cid in seen_case_ids if cid not in required_cases]
        if extra_cases:
            return {
                "verdict": "INCONCLUSIVE",
                "reason": f"EXTRA_CASES: unexpected {extra_cases}",
                "details": {"extra_cases": extra_cases},
            }

        # 4. Validate Each Case's Numeric vs Boolean Results and Cleanup
        for cid in required_cases:
            c = cases_by_id[cid]
            hv_map_return = c.get("hv_map_return")
            hv_map_success = c.get("hv_map_success")

            # Map executed check
            if hv_map_return is None or hv_map_success is None or not isinstance(hv_map_return, int) or not isinstance(hv_map_success, bool):
                return {
                    "verdict": "INCONCLUSIVE",
                    "reason": f"CASE_{cid}_MAP_NOT_EXECUTED_OR_INVALID (hv_map_return={hv_map_return}, hv_map_success={hv_map_success})",
                    "details": c,
                }

            # Map consistency
            if (hv_map_return == HV_SUCCESS) != (hv_map_success is True):
                return {
                    "verdict": "INCONCLUSIVE",
                    "reason": f"CASE_{cid}_MAP_RESULT_CONFLICT (hv_map_return={hv_map_return}, hv_map_success={hv_map_success})",
                    "details": c,
                }

            unmap_called = c.get("unmap_called")
            if not isinstance(unmap_called, bool):
                return {
                    "verdict": "INCONCLUSIVE",
                    "reason": f"CASE_{cid}_UNMAP_CALLED_INVALID",
                    "details": c,
                }

            if hv_map_success is True:
                if not unmap_called:
                    return {
                        "verdict": "CLEANUP_FAILURE",
                        "reason": f"CASE_{cid}_UNMAP_NOT_CALLED_AFTER_SUCCESSFUL_MAP",
                        "details": c,
                    }
                hv_unmap_return = c.get("hv_unmap_return")
                hv_unmap_success = c.get("hv_unmap_success")
                if hv_unmap_return is None or not isinstance(hv_unmap_return, int):
                    return {
                        "verdict": "CLEANUP_FAILURE",
                        "reason": f"CASE_{cid}_HV_UNMAP_FAILED (hv_return={hv_unmap_return})",
                        "details": c,
                    }
                if hv_unmap_success is not None:
                    if not isinstance(hv_unmap_success, bool) or ((hv_unmap_return == HV_SUCCESS) != (hv_unmap_success is True)):
                        return {
                            "verdict": "INCONCLUSIVE",
                            "reason": f"CASE_{cid}_UNMAP_RESULT_CONFLICT",
                            "details": c,
                        }
                if hv_unmap_return != HV_SUCCESS:
                    return {
                        "verdict": "CLEANUP_FAILURE",
                        "reason": f"CASE_{cid}_HV_UNMAP_FAILED (hv_return={hv_unmap_return:#x})",
                        "details": c,
                    }
            else:
                if unmap_called is True:
                    return {
                        "verdict": "INCONCLUSIVE",
                        "reason": f"CASE_{cid}_UNMAP_CALLED_ON_FAILED_MAP",
                        "details": c,
                    }

            # munmap check: munmap_return must be explicitly 0, not None
            munmap_return = c.get("munmap_return")
            if munmap_return is None or not isinstance(munmap_return, int):
                return {
                    "verdict": "CLEANUP_FAILURE",
                    "reason": f"CASE_{cid}_MUNMAP_FAILED (munmap_ret={munmap_return})",
                    "details": c,
                }
            if munmap_return != 0:
                return {
                    "verdict": "CLEANUP_FAILURE",
                    "reason": f"CASE_{cid}_MUNMAP_FAILED (munmap_ret={munmap_return})",
                    "details": c,
                }

        # 5. Check VM Lifecycle: vm_destroy
        vm_destroy = data.get("vm_destroy")
        if not isinstance(vm_destroy, dict):
            return {
                "verdict": "CLEANUP_FAILURE",
                "reason": "HVF_VM_DESTROY_NOT_RECORDED",
                "details": {"vm_destroy": vm_destroy},
            }

        destroy_ret = vm_destroy.get("hv_return")
        destroy_success = vm_destroy.get("success")
        if not isinstance(destroy_ret, int) or not isinstance(destroy_success, bool):
            return {
                "verdict": "CLEANUP_FAILURE",
                "reason": "VM_DESTROY_FIELD_INVALID",
                "details": {"vm_destroy": vm_destroy},
            }
        if (destroy_ret == HV_SUCCESS) != (destroy_success is True):
            return {
                "verdict": "INCONCLUSIVE",
                "reason": f"VM_DESTROY_RESULT_CONFLICT (hv_return={destroy_ret}, success={destroy_success})",
                "details": {"vm_destroy": vm_destroy},
            }
        if destroy_ret != HV_SUCCESS:
            return {
                "verdict": "CLEANUP_FAILURE",
                "reason": f"HVF_VM_DESTROY_FAILED (hv_return={destroy_ret:#x})",
                "details": {"vm_destroy": vm_destroy},
            }

        # 6. Check Positive Controls (A and D)
        case_a = cases_by_id["A"]
        if not case_a.get("hv_map_success"):
            return {
                "verdict": "INCONCLUSIVE",
                "reason": f"POSITIVE_CONTROL_A_FAILED (hv_return={case_a.get('hv_map_return'):#x})",
                "details": {
                    "case_a": case_a,
                    "note": "Anonymous RWX mapping failed; HVF mapping baseline is non-functional",
                },
            }

        case_d = cases_by_id["D"]
        if not case_d.get("hv_map_success"):
            return {
                "verdict": "INCONCLUSIVE",
                "reason": f"POSITIVE_CONTROL_D_FAILED (hv_return={case_d.get('hv_map_return'):#x})",
                "details": {
                    "case_d": case_d,
                    "note": "File-backed RWX mapping failed; file mapping baseline is non-functional",
                },
            }

        # 7. Evaluate target Case B
        case_b = cases_by_id["B"]
        case_c = cases_by_id["C"]

        if case_b.get("hv_map_success"):
            return {
                "verdict": "ADMITTED",
                "reason": "RO_HOST_MAPPING_ADMITTED",
                "details": {
                    "case_b": case_b,
                    "case_c": case_c,
                    "note": "HVF kernel admitted host PROT_READ file mapping with HV_MEMORY_READ.",
                },
            }
        else:
            return {
                "verdict": "REJECTED",
                "reason": f"RO_HOST_MAPPING_REJECTED (hv_return={case_b.get('hv_map_return'):#x})",
                "details": {
                    "case_b": case_b,
                    "case_c": case_c,
                    "note": "HVF kernel rejected host PROT_READ file mapping with HV_MEMORY_READ while positive controls A & D succeeded.",
                },
            }


if __name__ == "__main__":
    import sys

    classifier = ProbeClassifier()
    content = sys.stdin.read()
    data = classifier.parse_input(content)
    result = classifier.classify(data)
    print(json.dumps(result, indent=2))
