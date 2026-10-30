#!/usr/bin/env python3
"""
Unit tests for audit_proton.py
Verifies ELF64 (AArch64) and PE (ARM64 / ARM64EC) static auditing logic.
"""

import unittest
import struct
import tempfile
import os
from scripts.proton.audit_proton import BinaryAuditor

class TestAuditProton(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_synthetic_elf64_aarch64(self):
        # Create minimal valid ELF64 AArch64 executable header with PT_INTERP and PT_DYNAMIC
        elf_path = os.path.join(self.temp_dir.name, "test_wine64")

        # e_ident: 16 bytes: \x7fELF, 2 (64-bit), 1 (little endian), 1 (ver), 0 (sysv), 0...
        e_ident = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 8
        e_type = 2 # ET_EXEC
        e_machine = 183 # EM_AARCH64
        e_version = 1
        e_entry = 0x400000
        e_phoff = 64 # phdr follows immediately
        e_shoff = 0
        e_flags = 0
        e_ehsize = 64
        e_phentsize = 56
        e_phnum = 2
        e_shentsize = 64
        e_shnum = 0
        e_shstrndx = 0

        ehdr = struct.pack(
            "<16sHHIQQQIHHHHHH",
            e_ident, e_type, e_machine, e_version, e_entry,
            e_phoff, e_shoff, e_flags, e_ehsize, e_phentsize,
            e_phnum, e_shentsize, e_shnum, e_shstrndx
        )

        interp_str = b"/lib/ld-linux-aarch64.so.1\x00"
        interp_offset = 64 + 56 * 2 # 176

        # Phdr 1: PT_INTERP
        # Elf64_Phdr: IIQQQQQQ (p_type, p_flags, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_align)
        phdr1 = struct.pack(
            "<IIQQQQQQ",
            3, 4, interp_offset, 0x400000 + interp_offset, 0, len(interp_str), len(interp_str), 1
        )
        # Phdr 2: PT_LOAD
        phdr2 = struct.pack(
            "<IIQQQQQQ",
            1, 5, 0, 0x400000, 0, 512, 512, 0x1000
        )

        with open(elf_path, "wb") as f:
            f.write(ehdr)
            f.write(phdr1)
            f.write(phdr2)
            f.seek(interp_offset)
            f.write(interp_str)

        auditor = BinaryAuditor(elf_path)
        res = auditor.audit()

        self.assertEqual(res["format"], "ELF")
        self.assertEqual(res["details"]["class"], "ELF64")
        self.assertEqual(res["details"]["machine_id"], 183)
        self.assertTrue(res["details"]["is_native_arm64"])
        self.assertEqual(res["details"]["pt_interp"], "/lib/ld-linux-aarch64.so.1")

    def test_synthetic_pe_arm64ec(self):
        # Create minimal synthetic PE header with IMAGE_FILE_MACHINE_ARM64EC (0xa641)
        pe_path = os.path.join(self.temp_dir.name, "test_fex.dll")

        # DOS Header: MZ, e_lfanew at 0x3C = 64
        dos_hdr = b"MZ" + b"\x00" * 58 + struct.pack("<I", 64)
        
        # PE Signature
        pe_sig = b"PE\x00\x00"

        # COFF File Header: Machine (H), NumSections (H), TimeDate (I), SymPtr (I), NumSym (I), OptHdrSize (H), Char (H)
        coff_hdr = struct.pack(
            "<HHIIIHH",
            0xa641, 1, 0, 0, 0, 112, 0x2000 # ARM64EC, DLL
        )

        # Optional Header: magic PE32+ (0x20b)
        opt_hdr = struct.pack("<H", 0x20b) + b"\x00" * 110

        with open(pe_path, "wb") as f:
            f.write(dos_hdr)
            f.write(pe_sig)
            f.write(coff_hdr)
            f.write(opt_hdr)

        auditor = BinaryAuditor(pe_path)
        res = auditor.audit()

        self.assertEqual(res["format"], "PE")
        self.assertEqual(res["details"]["machine_id"], "0xa641")
        self.assertTrue(res["details"]["is_arm64ec"])
        self.assertEqual(res["details"]["opt_header_magic"], "PE32+ (64-bit)")


if __name__ == "__main__":
    unittest.main()
