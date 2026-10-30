#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for explicit runtime selection and runtime descriptor in scripts/backend/bundle.py & cli.py.
Validates:
- Default elfuse is original upstream clean
- Explicit --elfuse selection supports verified derived binaries (e.g. elfuse-fex-derived)
- Runtime descriptor captures path, sha256, flavor ('original' vs 'derived'), source baseline identity
- Rejection of paths outside lab (lab-local requirement)
- Rejection of non-existent, non-executable, or non-Mach-O binaries
- CLI --elfuse flag integration and non-zero exit on BLOCKED
- Plan-only mode guarantees zero subprocess execution
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

LAB = Path(__file__).resolve().parents[2]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts.backend.bundle import build_plan, get_elfuse_descriptor


class TestRuntimeSelection(unittest.TestCase):
    def setUp(self):
        self.manifest = LAB / "artifacts/public-proton/bundle.json"
        self.sysroot = LAB / "fixtures/runtime/sysroot"
        self.prefix = LAB / "fixtures/runtime/backend-compat/pfx"
        self.orig_elfuse = LAB / "sources/elfuse/build/elfuse"
        self.fex_derived_elfuse = LAB / "sources/elfuse-fex-derived/build/elfuse"
        self.futex_derived_elfuse = LAB / "sources/elfuse-derived/build/elfuse"

    def test_default_elfuse_is_original(self):
        """Default plan without explicit elfuse must select original pinned binary."""
        plan = build_plan(self.manifest, self.sysroot, self.prefix, ["test.exe"], engine="wine")
        self.assertEqual(plan["status"], "PLAN_READY")
        self.assertFalse(plan["execution_performed"])
        self.assertEqual(plan["argv"][0], str(self.orig_elfuse))

        descriptor = plan.get("runtime_descriptor")
        self.assertIsNotNone(descriptor)
        self.assertEqual(descriptor["flavor"], "original")
        self.assertEqual(descriptor["source_baseline"], "ORIGINAL_UPSTREAM_CLEAN")
        self.assertEqual(descriptor["path"], str(self.orig_elfuse))
        self.assertEqual(
            descriptor["sha256"],
            "dd5dae9ebe3c993ee16320f100d0ad552e5bdd60f31c3c5a9b325fdfd80a72e7",
        )

    def test_explicit_derived_elfuse_selection(self):
        """Explicit elfuse_path selects the derived binary with correct flavor and baseline."""
        plan = build_plan(
            self.manifest,
            self.sysroot,
            self.prefix,
            ["test.exe"],
            engine="wine",
            elfuse_path=self.fex_derived_elfuse,
        )
        self.assertEqual(plan["status"], "PLAN_READY")
        self.assertFalse(plan["execution_performed"])
        self.assertEqual(plan["argv"][0], str(self.fex_derived_elfuse))

        descriptor = plan.get("runtime_descriptor")
        self.assertIsNotNone(descriptor)
        self.assertEqual(descriptor["flavor"], "derived")
        self.assertEqual(descriptor["source_baseline"], "FEX_LAYOUT_ONLY_DERIVED")
        self.assertEqual(descriptor["path"], str(self.fex_derived_elfuse))
        self.assertEqual(
            descriptor["sha256"],
            "0079fc5d9185103b1f1bccf0b22b712d6109f9ac19dc53de497a7b3e3bb60ba7",
        )

    def test_explicit_futex_derived_selection(self):
        """Explicit selection of futex-derived elfuse."""
        plan = build_plan(
            self.manifest,
            self.sysroot,
            self.prefix,
            ["test.exe"],
            engine="wine",
            elfuse_path=self.futex_derived_elfuse,
        )
        self.assertEqual(plan["status"], "PLAN_READY")
        descriptor = plan.get("runtime_descriptor")
        self.assertIsNotNone(descriptor)
        self.assertEqual(descriptor["flavor"], "derived")
        self.assertEqual(descriptor["source_baseline"], "FUTEX_PATCHED_DERIVED")
        self.assertEqual(
            descriptor["sha256"],
            "ff3904318354d6dc4b8e17482fd83cd512b3156227d296e0c0e7c97ff6dcb21f",
        )

    def test_outside_lab_elfuse_rejected(self):
        """Paths outside lab must be blocked with lab-local error."""
        plan = build_plan(
            self.manifest,
            self.sysroot,
            self.prefix,
            ["test.exe"],
            engine="wine",
            elfuse_path=Path("/usr/bin/true"),
        )
        self.assertEqual(plan["status"], "BLOCKED")
        self.assertIn("lab-local", plan["reason"].lower())

    def test_nonexistent_elfuse_rejected(self):
        """Non-existent elfuse path must be blocked."""
        bad_path = LAB / "sources/elfuse-nonexistent/build/elfuse"
        plan = build_plan(
            self.manifest,
            self.sysroot,
            self.prefix,
            ["test.exe"],
            engine="wine",
            elfuse_path=bad_path,
        )
        self.assertEqual(plan["status"], "BLOCKED")
        self.assertIn("missing", plan["reason"].lower())

    def test_non_executable_elfuse_rejected(self):
        """Non-executable file must be blocked."""
        with tempfile.NamedTemporaryFile(dir=LAB / "logs/backend-runtime-selection", delete=False) as tf:
            tf.write(b"\xcf\xfa\xed\xfe" + b"\x00" * 64)
            tf_path = Path(tf.name)
        try:
            os.chmod(tf_path, 0o644)  # Not executable
            plan = build_plan(
                self.manifest,
                self.sysroot,
                self.prefix,
                ["test.exe"],
                engine="wine",
                elfuse_path=tf_path,
            )
            self.assertEqual(plan["status"], "BLOCKED")
            self.assertIn("executable", plan["reason"].lower())
        finally:
            tf_path.unlink(missing_ok=True)

    def test_non_macho_elfuse_rejected(self):
        """Executable file that is not a Mach-O binary must be blocked."""
        with tempfile.NamedTemporaryFile(dir=LAB / "logs/backend-runtime-selection", delete=False) as tf:
            tf.write(b"#!/bin/sh\necho fake\n")
            tf_path = Path(tf.name)
        try:
            os.chmod(tf_path, 0o755)
            plan = build_plan(
                self.manifest,
                self.sysroot,
                self.prefix,
                ["test.exe"],
                engine="wine",
                elfuse_path=tf_path,
            )
            self.assertEqual(plan["status"], "BLOCKED")
            self.assertIn("mach-o", plan["reason"].lower())
        finally:
            tf_path.unlink(missing_ok=True)

    def test_cli_explicit_elfuse_plan_only(self):
        """CLI with --elfuse outputs plan with derived descriptor and exits 0 in plan-only mode."""
        cmd = [
            sys.executable,
            "-m",
            "scripts.backend.cli",
            "--engine",
            "wine",
            "--elfuse",
            str(self.fex_derived_elfuse),
        ]
        proc = subprocess.run(cmd, cwd=LAB, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, f"CLI failed: {proc.stderr}")
        data = json.loads(proc.stdout)
        self.assertEqual(data["status"], "PLAN_READY")
        self.assertFalse(data["execution_performed"])
        self.assertEqual(data["runtime_descriptor"]["flavor"], "derived")
        self.assertEqual(data["runtime_descriptor"]["source_baseline"], "FEX_LAYOUT_ONLY_DERIVED")

    def test_cli_blocked_elfuse_returns_exit_20(self):
        """CLI with invalid/outside elfuse returns exit 20 and BLOCKED status."""
        cmd = [
            sys.executable,
            "-m",
            "scripts.backend.cli",
            "--engine",
            "wine",
            "--elfuse",
            "/usr/bin/true",
        ]
        proc = subprocess.run(cmd, cwd=LAB, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 20)
        data = json.loads(proc.stdout)
        self.assertEqual(data["status"], "BLOCKED")

    def test_replaced_binary_at_original_path_marked_unverified(self):
        """Even if file is located at sources/elfuse/build/elfuse, if its hash does NOT match
        the original pinned upstream commit hash, it MUST NOT be declared ORIGINAL_UPSTREAM_CLEAN."""
        # Use a copy of the derived elfuse at a temporary mock original path
        mock_orig = LAB / "logs/backend-runtime-selection/mock_replaced_elfuse"
        mock_orig.write_bytes(self.fex_derived_elfuse.read_bytes())
        os.chmod(mock_orig, 0o755)
        try:
            descriptor = get_elfuse_descriptor(mock_orig)
            self.assertEqual(descriptor["flavor"], "derived")
            # Must match derived hash, not original clean
            self.assertNotEqual(descriptor["source_baseline"], "ORIGINAL_UPSTREAM_CLEAN")
            self.assertEqual(descriptor["source_baseline"], "FEX_LAYOUT_ONLY_DERIVED")
        finally:
            mock_orig.unlink(missing_ok=True)

    def test_short_4byte_magic_only_rejected(self):
        """File with only 4 bytes of magic (size < 32 bytes) must be rejected as invalid header."""
        with tempfile.NamedTemporaryFile(dir=LAB / "logs/backend-runtime-selection", delete=False) as tf:
            tf.write(b"\xcf\xfa\xed\xfe")  # 4 bytes only
            tf_path = Path(tf.name)
        try:
            os.chmod(tf_path, 0o755)
            plan = build_plan(self.manifest, self.sysroot, self.prefix, ["test.exe"], engine="wine", elfuse_path=tf_path)
            self.assertEqual(plan["status"], "BLOCKED")
            self.assertIn("mach-o", plan["reason"].lower())
        finally:
            tf_path.unlink(missing_ok=True)

    def test_fat_cafebabe_rejected_as_unsupported(self):
        """Universal/FAT binary or Java (0xcafebabe) must be rejected as unsupported."""
        with tempfile.NamedTemporaryFile(dir=LAB / "logs/backend-runtime-selection", delete=False) as tf:
            tf.write(b"\xca\xfe\xba\xbe" + b"\x00" * 60)
            tf_path = Path(tf.name)
        try:
            os.chmod(tf_path, 0o755)
            plan = build_plan(self.manifest, self.sysroot, self.prefix, ["test.exe"], engine="wine", elfuse_path=tf_path)
            self.assertEqual(plan["status"], "BLOCKED")
            self.assertIn("fat", plan["reason"].lower())
        finally:
            tf_path.unlink(missing_ok=True)

    def test_non_arm64_or_non_execute_macho_rejected(self):
        """Mach-O with wrong filetype (e.g. MH_OBJECT=1 instead of MH_EXECUTE=2) must be rejected."""
        import struct
        # magic: 0xfeedfacf, cputype: ARM64 (0x100000c), cpusubtype: 0, filetype: 1 (MH_OBJECT), ncmds: 1, sizeofcmds: 8, flags: 0, reserved: 0
        fake_hdr = struct.pack("<IIIIIIII", 0xfeedfacf, 0x100000c, 0, 1, 1, 8, 0, 0) + b"\x00" * 32
        with tempfile.NamedTemporaryFile(dir=LAB / "logs/backend-runtime-selection", delete=False) as tf:
            tf.write(fake_hdr)
            tf_path = Path(tf.name)
        try:
            os.chmod(tf_path, 0o755)
            plan = build_plan(self.manifest, self.sysroot, self.prefix, ["test.exe"], engine="wine", elfuse_path=tf_path)
            self.assertEqual(plan["status"], "BLOCKED")
            self.assertIn("mh_execute", plan["reason"].lower())
        finally:
            tf_path.unlink(missing_ok=True)

    def test_descriptor_records_commit_and_execution_evidence(self):
        """Descriptor must record pinned commit, patches list, and explicit execution_evidence=NOT_CHECKED."""
        orig_descriptor = get_elfuse_descriptor(self.orig_elfuse)
        self.assertIn("commit", orig_descriptor)
        self.assertEqual(orig_descriptor["commit"], "8612033dab8dc60728f604a4ea0441895fc16d39")
        self.assertEqual(orig_descriptor["patches"], [])
        self.assertEqual(orig_descriptor["execution_evidence"], "NOT_CHECKED")

        derived_descriptor = get_elfuse_descriptor(self.fex_derived_elfuse)
        self.assertEqual(derived_descriptor["commit"], "8612033dab8dc60728f604a4ea0441895fc16d39")
        self.assertIn("layout_shift", derived_descriptor["patches"])
        self.assertEqual(derived_descriptor["execution_evidence"], "NOT_CHECKED")


if __name__ == "__main__":
    unittest.main()
