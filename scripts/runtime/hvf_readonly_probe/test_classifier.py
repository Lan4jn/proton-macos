#!/usr/bin/env python3
"""
test_classifier.py - Unit test suite for HVF probe classifier.

Covers:
1. R-only map 成功 + controls -> ADMITTED
2. R-only map 失败 + controls -> REJECTED
3. Controls 失败 (Case A / Case D / vm_create) -> INCONCLUSIVE
4. 清理失败 (unmap / munmap / vm_destroy) -> CLEANUP_FAILURE
5. 缺 case (incomplete sequential run) -> INCONCLUSIVE
6. JSON and JSONL parsing
"""

import json
import unittest
from classifier import ProbeClassifier, HV_SUCCESS


class TestProbeClassifier(unittest.TestCase):
    def setUp(self):
        self.classifier = ProbeClassifier()

    def _make_base_payload(self):
        return {
            "vm_create": {"hv_return": 0, "success": True},
            "cases": [
                {
                    "case_id": "A",
                    "description": "anon_rw_to_rwx",
                    "file_path": None,
                    "file_access": "NONE",
                    "host_prot": "PROT_READ|PROT_WRITE",
                    "host_flags": "MAP_ANON|MAP_PRIVATE",
                    "host_addr": "0x104000000",
                    "host_page_size": 16384,
                    "is_aligned": True,
                    "ipa": "0x20000000",
                    "size": 65536,
                    "hv_flags": 7,
                    "hv_map_return": 0,
                    "hv_map_success": True,
                    "unmap_called": True,
                    "hv_unmap_return": 0,
                    "hv_unmap_success": True,
                    "munmap_return": 0,
                    "status": "OK",
                },
                {
                    "case_id": "B",
                    "description": "file_ro_to_ro",
                    "file_path": "/tmp/test.seed",
                    "file_access": "O_RDONLY",
                    "host_prot": "PROT_READ",
                    "host_flags": "MAP_SHARED",
                    "host_addr": "0x104020000",
                    "host_page_size": 16384,
                    "is_aligned": True,
                    "ipa": "0x20000000",
                    "size": 65536,
                    "hv_flags": 1,
                    "hv_map_return": 0,
                    "hv_map_success": True,
                    "unmap_called": True,
                    "hv_unmap_return": 0,
                    "hv_unmap_success": True,
                    "munmap_return": 0,
                    "status": "OK",
                },
                {
                    "case_id": "C",
                    "description": "file_ro_to_rwx_contrast",
                    "file_path": "/tmp/test.seed",
                    "file_access": "O_RDONLY",
                    "host_prot": "PROT_READ",
                    "host_flags": "MAP_SHARED",
                    "host_addr": "0x104040000",
                    "host_page_size": 16384,
                    "is_aligned": True,
                    "ipa": "0x20000000",
                    "size": 65536,
                    "hv_flags": 7,
                    "hv_map_return": 0xFAE94003,
                    "hv_map_success": False,
                    "unmap_called": False,
                    "hv_unmap_return": None,
                    "hv_unmap_success": None,
                    "munmap_return": 0,
                    "status": "MAP_FAILED",
                },
                {
                    "case_id": "D",
                    "description": "file_rw_to_rwx",
                    "file_path": "/tmp/test.seed",
                    "file_access": "O_RDWR",
                    "host_prot": "PROT_READ|PROT_WRITE",
                    "host_flags": "MAP_SHARED",
                    "host_addr": "0x104060000",
                    "host_page_size": 16384,
                    "is_aligned": True,
                    "ipa": "0x20000000",
                    "size": 65536,
                    "hv_flags": 7,
                    "hv_map_return": 0,
                    "hv_map_success": True,
                    "unmap_called": True,
                    "hv_unmap_return": 0,
                    "hv_unmap_success": True,
                    "munmap_return": 0,
                    "status": "OK",
                },
            ],
            "vm_destroy": {"hv_return": 0, "success": True},
        }

    # 1. R-only map 成功 + controls -> ADMITTED
    def test_ronly_map_success_with_controls(self):
        payload = self._make_base_payload()
        result = self.classifier.classify(payload)
        self.assertEqual(result["verdict"], "ADMITTED")
        self.assertEqual(result["reason"], "RO_HOST_MAPPING_ADMITTED")

    # 2. R-only map 失败 + controls -> REJECTED
    def test_ronly_map_failure_with_controls(self):
        payload = self._make_base_payload()
        # Case B fails to map
        payload["cases"][1]["hv_map_return"] = 0xFAE94007  # HV_DENIED
        payload["cases"][1]["hv_map_success"] = False
        payload["cases"][1]["unmap_called"] = False
        payload["cases"][1]["hv_unmap_return"] = None
        payload["cases"][1]["hv_unmap_success"] = None
        payload["cases"][1]["status"] = "MAP_FAILED"

        result = self.classifier.classify(payload)
        self.assertEqual(result["verdict"], "REJECTED")
        self.assertIn("RO_HOST_MAPPING_REJECTED", result["reason"])

    # 3. Controls 失败:
    # 3a. Case A controls failure -> INCONCLUSIVE
    def test_positive_control_a_failure(self):
        payload = self._make_base_payload()
        payload["cases"][0]["hv_map_return"] = 0xFAE94001
        payload["cases"][0]["hv_map_success"] = False
        payload["cases"][0]["unmap_called"] = False

        result = self.classifier.classify(payload)
        self.assertEqual(result["verdict"], "INCONCLUSIVE")
        self.assertIn("POSITIVE_CONTROL_A_FAILED", result["reason"])

    # 3b. Case D controls failure -> INCONCLUSIVE
    def test_positive_control_d_failure(self):
        payload = self._make_base_payload()
        payload["cases"][3]["hv_map_return"] = 0xFAE94001
        payload["cases"][3]["hv_map_success"] = False
        payload["cases"][3]["unmap_called"] = False

        result = self.classifier.classify(payload)
        self.assertEqual(result["verdict"], "INCONCLUSIVE")
        self.assertIn("POSITIVE_CONTROL_D_FAILED", result["reason"])

    # 3c. vm_create failure -> INCONCLUSIVE
    def test_vm_create_failure(self):
        payload = self._make_base_payload()
        payload["vm_create"]["hv_return"] = 0xFAE94007  # HV_DENIED
        payload["vm_create"]["success"] = False

        result = self.classifier.classify(payload)
        self.assertEqual(result["verdict"], "INCONCLUSIVE")
        self.assertIn("HVF_VM_CREATE_FAILED", result["reason"])

    # 4. 清理失败:
    # 4a. unmap failure
    def test_cleanup_unmap_failure(self):
        payload = self._make_base_payload()
        payload["cases"][1]["hv_unmap_return"] = 0xFAE94001  # unmap failed
        payload["cases"][1]["hv_unmap_success"] = False

        result = self.classifier.classify(payload)
        self.assertEqual(result["verdict"], "CLEANUP_FAILURE")
        self.assertIn("HV_UNMAP_FAILED", result["reason"])

    # 4b. munmap failure
    def test_cleanup_munmap_failure(self):
        payload = self._make_base_payload()
        payload["cases"][0]["munmap_return"] = -1

        result = self.classifier.classify(payload)
        self.assertEqual(result["verdict"], "CLEANUP_FAILURE")
        self.assertIn("MUNMAP_FAILED", result["reason"])

    # 4c. vm_destroy failure
    def test_cleanup_destroy_failure(self):
        payload = self._make_base_payload()
        payload["vm_destroy"]["hv_return"] = 0xFAE94001
        payload["vm_destroy"]["success"] = False

        result = self.classifier.classify(payload)
        self.assertEqual(result["verdict"], "CLEANUP_FAILURE")
        self.assertIn("HVF_VM_DESTROY_FAILED", result["reason"])

    # 5. 缺 case:
    # 5a. Missing Case D
    def test_missing_case(self):
        payload = self._make_base_payload()
        payload["cases"] = payload["cases"][:3]  # Only A, B, C

        result = self.classifier.classify(payload)
        self.assertEqual(result["verdict"], "INCONCLUSIVE")
        self.assertIn("MISSING_CASES", result["reason"])

    # 5b. Early abort (only Case A)
    def test_early_abort(self):
        payload = self._make_base_payload()
        payload["cases"] = payload["cases"][:1]  # Only A

        result = self.classifier.classify(payload)
        self.assertEqual(result["verdict"], "INCONCLUSIVE")
        self.assertIn("MISSING_CASES", result["reason"])

    # 6. JSONL streaming input parsing
    def test_jsonl_parsing(self):
        lines = [
            json.dumps({"event": "vm_create", "hv_return": 0, "success": True}),
            json.dumps({
                "event": "case_result",
                "case_id": "A",
                "hv_map_success": True,
                "hv_map_return": 0,
                "unmap_called": True,
                "hv_unmap_return": 0,
                "munmap_return": 0,
            }),
            json.dumps({
                "event": "case_result",
                "case_id": "B",
                "hv_map_success": True,
                "hv_map_return": 0,
                "unmap_called": True,
                "hv_unmap_return": 0,
                "munmap_return": 0,
            }),
            json.dumps({
                "event": "case_result",
                "case_id": "C",
                "hv_map_success": False,
                "hv_map_return": 0xFAE94003,
                "unmap_called": False,
                "hv_unmap_return": None,
                "munmap_return": 0,
            }),
            json.dumps({
                "event": "case_result",
                "case_id": "D",
                "hv_map_success": True,
                "hv_map_return": 0,
                "unmap_called": True,
                "hv_unmap_return": 0,
                "munmap_return": 0,
            }),
            json.dumps({"event": "vm_destroy", "hv_return": 0, "success": True}),
        ]
        jsonl_str = "\n".join(lines)
        parsed = self.classifier.parse_input(jsonl_str)
        result = self.classifier.classify(parsed)
        self.assertEqual(result["verdict"], "ADMITTED")

    # 7. Execution metadata bindings
    def test_nonzero_probe_returncode_inconclusive(self):
        payload = self._make_base_payload()
        result = self.classifier.classify(payload, probe_returncode=1)
        self.assertEqual(result["verdict"], "INCONCLUSIVE")
        self.assertIn("PROBE_PROCESS_FAILED", result["reason"])

    def test_timed_out_inconclusive(self):
        payload = self._make_base_payload()
        result = self.classifier.classify(payload, timed_out=True)
        self.assertEqual(result["verdict"], "INCONCLUSIVE")
        self.assertIn("EXECUTION_TIMED_OUT", result["reason"])

    def test_seed_hash_mismatch_inconclusive(self):
        payload = self._make_base_payload()
        result = self.classifier.classify(
            payload,
            seed_sha_before="1fde717d808c7e06c2e08ea843c4c8214ba82e63ff07ab731a2da3bd489e15de",
            seed_sha_after="modified_hash_1234567890abcdef1234567890abcdef1234567890abcdef123456"
        )
        self.assertEqual(result["verdict"], "INCONCLUSIVE")
        self.assertIn("SEED_HASH_MISMATCH", result["reason"])

    # 8. Structural and integrity robustness
    def test_duplicate_case_id_inconclusive(self):
        payload = self._make_base_payload()
        # Add duplicate case B
        payload["cases"].append(dict(payload["cases"][1]))
        result = self.classifier.classify(payload)
        self.assertEqual(result["verdict"], "INCONCLUSIVE")
        self.assertIn("DUPLICATE", result["reason"])

    def test_map_not_executed_case_b_inconclusive(self):
        """Case B has None or unexecuted hv_map_return: must be INCONCLUSIVE, not fake REJECTED."""
        payload = self._make_base_payload()
        payload["cases"][1]["hv_map_return"] = None
        payload["cases"][1]["hv_map_success"] = None
        payload["cases"][1]["status"] = "MMAP_FAILED"

        result = self.classifier.classify(payload)
        self.assertEqual(result["verdict"], "INCONCLUSIVE")
        self.assertNotIn("REJECTED", result["verdict"])

    def test_missing_munmap_return_fails(self):
        """munmap_return is None or missing: must NOT be treated as cleanup 0."""
        payload = self._make_base_payload()
        payload["cases"][0]["munmap_return"] = None

        result = self.classifier.classify(payload)
        self.assertEqual(result["verdict"], "CLEANUP_FAILURE")
        self.assertIn("MUNMAP", result["reason"])

    def test_missing_hv_unmap_when_map_succeeded(self):
        """hv_unmap_return is None when unmap_called is True: must be CLEANUP_FAILURE."""
        payload = self._make_base_payload()
        payload["cases"][0]["hv_unmap_return"] = None

        result = self.classifier.classify(payload)
        self.assertEqual(result["verdict"], "CLEANUP_FAILURE")
        self.assertIn("HV_UNMAP", result["reason"])

    def test_conflicting_map_numeric_and_bool(self):
        """hv_map_return=0 but hv_map_success=False must be INCONCLUSIVE conflict."""
        payload = self._make_base_payload()
        payload["cases"][0]["hv_map_return"] = 0
        payload["cases"][0]["hv_map_success"] = False

        result = self.classifier.classify(payload)
        self.assertEqual(result["verdict"], "INCONCLUSIVE")
        self.assertIn("CONFLICT", result["reason"])

    def test_conflicting_unmap_numeric_and_bool(self):
        """hv_unmap_return=0 but hv_unmap_success=False must be INCONCLUSIVE conflict."""
        payload = self._make_base_payload()
        payload["cases"][0]["hv_unmap_return"] = 0
        payload["cases"][0]["hv_unmap_success"] = False

        result = self.classifier.classify(payload)
        self.assertEqual(result["verdict"], "INCONCLUSIVE")
        self.assertIn("CONFLICT", result["reason"])

    def test_bytes_input_to_parse_input(self):
        """parse_input handles bytes cleanly without TypeError."""
        raw_bytes = b'{"event":"vm_create","hv_return":0,"success":true}\n'
        parsed = self.classifier.parse_input(raw_bytes)
        self.assertIsNotNone(parsed["vm_create"])
        self.assertEqual(parsed["vm_create"]["hv_return"], 0)


if __name__ == "__main__":
    unittest.main()
