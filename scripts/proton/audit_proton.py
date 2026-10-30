#!/usr/bin/env python3
"""
scripts/proton/audit_proton.py

ELF and PE Static Analyzer for ARM64 Proton binaries and runtime libraries.
Designed to audit:
- ELF binaries: Magic, Architecture (ARM64/AArch64, x86_64), PT_INTERP, DT_NEEDED, DT_RPATH/RUNPATH, GLIBC symbol versions (.gnu.version_r).
- PE binaries: Magic (MZ/PE), Machine (ARM64 0xAA64, ARM64EC 0xA641, AMD64 0x8664, i386 0x14C), Subsystem.
- Distinction between native ARM64 Linux components (wine64, wineserver, *.so) and emulated/Windows PE modules (ARM64EC / WOW64 PE).
Works with zero external dependencies (pure Python 3 standard library).
"""

import sys
import os
import struct
import json
import argparse
from typing import Dict, List, Any, Optional, Tuple

# ELF Constants
EI_MAG0 = 0
EI_MAG1 = 1
EI_MAG2 = 2
EI_MAG3 = 3
EI_CLASS = 4
EI_DATA = 5
EI_VERSION = 6
EI_OSABI = 7
EI_ABIVERSION = 8

ELFCLASS32 = 1
ELFCLASS64 = 2

ELFDATA2LSB = 1
ELFDATA2MSB = 2

PT_NULL = 0
PT_LOAD = 1
PT_DYNAMIC = 2
PT_INTERP = 3
PT_NOTE = 4
PT_SHLIB = 5
PT_PHDR = 6
PT_TLS = 7
PT_GNU_EH_FRAME = 0x6474e550
PT_GNU_STACK = 0x6474e551
PT_GNU_RELRO = 0x6474e552

DT_NULL = 0
DT_NEEDED = 1
DT_PLTRELSZ = 2
DT_PLTGOT = 3
DT_HASH = 4
DT_STRTAB = 5
DT_SYMTAB = 6
DT_RELA = 7
DT_RELASZ = 8
DT_RELAENT = 9
DT_STRSZ = 10
DT_SYMENT = 11
DT_INIT = 12
DT_FINI = 13
DT_SONAME = 14
DT_RPATH = 15
DT_SYMBOLIC = 16
DT_REL = 17
DT_RELSZ = 18
DT_RELENT = 19
DT_PLTREL = 20
DT_DEBUG = 21
DT_TEXTREL = 22
DT_JMPREL = 23
DT_BIND_NOW = 24
DT_INIT_ARRAY = 25
DT_FINI_ARRAY = 26
DT_INIT_ARRAYSZ = 27
DT_FINI_ARRAYSZ = 28
DT_RUNPATH = 29
DT_FLAGS = 30
DT_GNU_HASH = 0x6ffffef5
DT_VERSYM = 0x6ffffff0
DT_VERNEED = 0x6ffffffe
DT_VERNEEDNUM = 0x6fffffff

EM_386 = 3
EM_X86_64 = 62
EM_ARM = 40
EM_AARCH64 = 183

EM_MAP = {
    EM_386: "i386",
    EM_X86_64: "x86_64",
    EM_ARM: "ARM32",
    EM_AARCH64: "AArch64 (ARM64)",
}

# PE Constants
IMAGE_FILE_MACHINE_I386 = 0x014c
IMAGE_FILE_MACHINE_AMD64 = 0x8664
IMAGE_FILE_MACHINE_ARMNT = 0x01c4
IMAGE_FILE_MACHINE_ARM64 = 0xaa64
IMAGE_FILE_MACHINE_ARM64EC = 0xa641

PE_MACHINE_MAP = {
    IMAGE_FILE_MACHINE_I386: "i386 (x86 32-bit)",
    IMAGE_FILE_MACHINE_AMD64: "AMD64 (x86_64)",
    IMAGE_FILE_MACHINE_ARMNT: "ARM Thumb-2",
    IMAGE_FILE_MACHINE_ARM64: "ARM64",
    IMAGE_FILE_MACHINE_ARM64EC: "ARM64EC (ARM64 Emulation Compatible)",
}


class BinaryAuditor:
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.filesize = os.path.getsize(filepath)
        self.format: str = "Unknown"
        self.details: Dict[str, Any] = {}

    def audit(self) -> Dict[str, Any]:
        with open(self.filepath, "rb") as f:
            header = f.read(4)
            if header == b"\x7fELF":
                self.format = "ELF"
                self._audit_elf(f)
            elif header[:2] == b"MZ":
                self.format = "PE"
                self._audit_pe(f)
            else:
                self.format = "Unknown"
                self.details = {"error": "Unrecognized magic bytes"}

        return {
            "path": self.filepath,
            "filename": os.path.basename(self.filepath),
            "size": self.filesize,
            "format": self.format,
            "details": self.details,
        }

    def _audit_elf(self, f) -> None:
        f.seek(0)
        e_ident = f.read(16)
        ei_class = e_ident[EI_CLASS]
        ei_data = e_ident[EI_DATA]

        endian = "<" if ei_data == ELFDATA2LSB else ">"
        is_64bit = ei_class == ELFCLASS64

        if is_64bit:
            # 64-bit ELF Header
            # 16s H H I Q Q Q I H H H H H H
            fmt = f"{endian}16sHHIQQQIHHHHHH"
            f.seek(0)
            data = f.read(struct.calcsize(fmt))
            if len(data) < struct.calcsize(fmt):
                self.details = {"error": "Truncated ELF64 header"}
                return
            (
                ident,
                e_type,
                e_machine,
                e_version,
                e_entry,
                e_phoff,
                e_shoff,
                e_flags,
                e_ehsize,
                e_phentsize,
                e_phnum,
                e_shentsize,
                e_shnum,
                e_shstrndx,
            ) = struct.unpack(fmt, data)
        else:
            # 32-bit ELF Header
            fmt = f"{endian}16sHHIIIIIHHHHHH"
            f.seek(0)
            data = f.read(struct.calcsize(fmt))
            if len(data) < struct.calcsize(fmt):
                self.details = {"error": "Truncated ELF32 header"}
                return
            (
                ident,
                e_type,
                e_machine,
                e_version,
                e_entry,
                e_phoff,
                e_shoff,
                e_flags,
                e_ehsize,
                e_phentsize,
                e_phnum,
                e_shentsize,
                e_shnum,
                e_shstrndx,
            ) = struct.unpack(fmt, data)

        machine_name = EM_MAP.get(e_machine, f"Unknown ({e_machine})")
        type_str = "ET_EXEC" if e_type == 2 else ("ET_DYN" if e_type == 3 else f"Type({e_type})")

        interp: Optional[str] = None
        dynamic_offset: Optional[int] = None
        dynamic_size: Optional[int] = None

        # Parse Program Headers
        for i in range(e_phnum):
            f.seek(e_phoff + i * e_phentsize)
            if is_64bit:
                # Elf64_Phdr: IIQQQQQQ (p_type, p_flags, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_align)
                ph_data = f.read(56)
                if len(ph_data) < 56:
                    break
                p_type, p_flags, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_align = struct.unpack(
                    f"{endian}IIQQQQQQ", ph_data
                )
            else:
                # Elf32_Phdr: IIIIIIII (p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_flags, p_align)
                ph_data = f.read(32)
                if len(ph_data) < 32:
                    break
                p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_flags, p_align = struct.unpack(
                    f"{endian}IIIIIIII", ph_data
                )

            if p_type == PT_INTERP:
                f.seek(p_offset)
                raw_interp = f.read(p_filesz)
                interp = raw_interp.split(b"\x00")[0].decode("utf-8", errors="replace")
            elif p_type == PT_DYNAMIC:
                dynamic_offset = p_offset
                dynamic_size = p_filesz

        # Parse Section Headers to locate .dynstr and .gnu.version_r if possible
        dynstr_data: Optional[bytes] = None
        verneed_data: Optional[bytes] = None
        verneed_sh_offset: Optional[int] = None
        verneed_sh_size: Optional[int] = None

        if e_shoff > 0 and e_shnum > 0 and e_shstrndx < e_shnum:
            # Read section header string table offset
            sh_fmt = f"{endian}IIQQQQIIQQ" if is_64bit else f"{endian}IIIIIIIIII"
            sh_size = struct.calcsize(sh_fmt)

            f.seek(e_shoff + e_shstrndx * sh_size)
            shstr_data = f.read(sh_size)
            if len(shstr_data) == sh_size:
                if is_64bit:
                    _, _, _, _, sh_offset, sh_filesz, _, _, _, _ = struct.unpack(sh_fmt, shstr_data)
                else:
                    _, _, _, _, sh_offset, sh_filesz, _, _, _, _ = struct.unpack(sh_fmt, shstr_data)
                f.seek(sh_offset)
                shstrtab = f.read(sh_filesz)

                def get_shname(idx: int) -> str:
                    if idx >= len(shstrtab):
                        return ""
                    end = shstrtab.find(b"\x00", idx)
                    return shstrtab[idx:end].decode("utf-8", errors="replace")

                for i in range(e_shnum):
                    f.seek(e_shoff + i * sh_size)
                    raw_sh = f.read(sh_size)
                    if len(raw_sh) < sh_size:
                        continue
                    if is_64bit:
                        sh_name, sh_type, sh_flags, sh_addr, s_offset, s_size, sh_link, sh_info, sh_addralign, sh_entsize = struct.unpack(sh_fmt, raw_sh)
                    else:
                        sh_name, sh_type, sh_flags, sh_addr, s_offset, s_size, sh_link, sh_info, sh_addralign, sh_entsize = struct.unpack(sh_fmt, raw_sh)

                    name = get_shname(sh_name)
                    if name == ".dynstr":
                        f.seek(s_offset)
                        dynstr_data = f.read(s_size)
                    elif name == ".gnu.version_r":
                        f.seek(s_offset)
                        verneed_data = f.read(s_size)
                        verneed_sh_offset = s_offset
                        verneed_sh_size = s_size

        dt_needed: List[str] = []
        dt_rpath: Optional[str] = None
        dt_runpath: Optional[str] = None
        dt_soname: Optional[str] = None

        # Parse DYNAMIC section
        if dynamic_offset is not None and dynamic_size is not None:
            entry_fmt = f"{endian}qQ" if is_64bit else f"{endian}iI"
            entry_size = struct.calcsize(entry_fmt)
            f.seek(dynamic_offset)
            dyn_bytes = f.read(dynamic_size)

            strtab_ptr: Optional[int] = None
            strsz: Optional[int] = None
            needed_offsets: List[int] = []
            rpath_offset: Optional[int] = None
            runpath_offset: Optional[int] = None
            soname_offset: Optional[int] = None

            for i in range(0, len(dyn_bytes) - entry_size + 1, entry_size):
                d_tag, d_val = struct.unpack(entry_fmt, dyn_bytes[i : i + entry_size])
                if d_tag == DT_NULL:
                    break
                elif d_tag == DT_NEEDED:
                    needed_offsets.append(d_val)
                elif d_tag == DT_RPATH:
                    rpath_offset = d_val
                elif d_tag == DT_RUNPATH:
                    runpath_offset = d_val
                elif d_tag == DT_SONAME:
                    soname_offset = d_val
                elif d_tag == DT_STRTAB:
                    strtab_ptr = d_val
                elif d_tag == DT_STRSZ:
                    strsz = d_val

            # If we didn't find dynstr from section headers, try reading it from file
            # In typical ELF, if PT_LOAD mapping is known, strtab_ptr is a virtual address.
            # But section header .dynstr is usually much more reliable!
            if dynstr_data:
                for off in needed_offsets:
                    if off < len(dynstr_data):
                        end = dynstr_data.find(b"\x00", off)
                        if end != -1:
                            dt_needed.append(dynstr_data[off:end].decode("utf-8", errors="replace"))
                if rpath_offset is not None and rpath_offset < len(dynstr_data):
                    end = dynstr_data.find(b"\x00", rpath_offset)
                    if end != -1:
                        dt_rpath = dynstr_data[rpath_offset:end].decode("utf-8", errors="replace")
                if runpath_offset is not None and runpath_offset < len(dynstr_data):
                    end = dynstr_data.find(b"\x00", runpath_offset)
                    if end != -1:
                        dt_runpath = dynstr_data[runpath_offset:end].decode("utf-8", errors="replace")
                if soname_offset is not None and soname_offset < len(dynstr_data):
                    end = dynstr_data.find(b"\x00", soname_offset)
                    if end != -1:
                        dt_soname = dynstr_data[soname_offset:end].decode("utf-8", errors="replace")

        # Parse GLIBC version requirements from .gnu.version_r
        glibc_versions: List[str] = []
        if verneed_data and dynstr_data:
            glibc_versions = self._parse_verneed(verneed_data, dynstr_data, endian)

        self.details = {
            "class": "ELF64" if is_64bit else "ELF32",
            "endian": "little-endian" if endian == "<" else "big-endian",
            "machine": machine_name,
            "machine_id": e_machine,
            "type": type_str,
            "entry_point": hex(e_entry),
            "pt_interp": interp,
            "dt_soname": dt_soname,
            "dt_needed": dt_needed,
            "dt_rpath": dt_rpath,
            "dt_runpath": dt_runpath,
            "glibc_symbol_versions": sorted(list(set(glibc_versions))),
            "is_native_arm64": (e_machine == EM_AARCH64),
        }

    def _parse_verneed(self, data: bytes, dynstr: bytes, endian: str) -> List[str]:
        # Elfxx_Verneed:
        # vn_version(H), vn_cnt(H), vn_file(I), vn_aux(I), vn_next(I)
        versions: List[str] = []
        vn_fmt = f"{endian}HHIII"
        vn_size = struct.calcsize(vn_fmt)
        vna_fmt = f"{endian}IHHII"
        vna_size = struct.calcsize(vna_fmt)

        curr_vn = 0
        while curr_vn + vn_size <= len(data):
            vn_version, vn_cnt, vn_file, vn_aux, vn_next = struct.unpack(
                vn_fmt, data[curr_vn : curr_vn + vn_size]
            )
            file_name = ""
            if vn_file < len(dynstr):
                end = dynstr.find(b"\x00", vn_file)
                file_name = dynstr[vn_file:end].decode("utf-8", errors="replace")

            curr_vna = curr_vn + vn_aux
            for _ in range(vn_cnt):
                if curr_vna + vna_size > len(data):
                    break
                vna_hash, vna_flags, vna_other, vna_name, vna_next = struct.unpack(
                    vna_fmt, data[curr_vna : curr_vna + vna_size]
                )
                ver_name = ""
                if vna_name < len(dynstr):
                    end = dynstr.find(b"\x00", vna_name)
                    ver_name = dynstr[vna_name:end].decode("utf-8", errors="replace")
                if ver_name:
                    versions.append(ver_name)
                if vna_next == 0:
                    break
                curr_vna += vna_next

            if vn_next == 0:
                break
            curr_vn += vn_next

        return versions

    def _audit_pe(self, f) -> None:
        f.seek(0x3C)
        e_lfanew_bytes = f.read(4)
        if len(e_lfanew_bytes) < 4:
            self.details = {"error": "Truncated DOS header"}
            return
        e_lfanew = struct.unpack("<I", e_lfanew_bytes)[0]

        f.seek(e_lfanew)
        pe_sig = f.read(4)
        if pe_sig != b"PE\x00\x00":
            self.details = {"error": "Invalid PE signature offset"}
            return

        # COFF File Header
        # Machine (H), NumberOfSections (H), TimeDateStamp (I), PointerToSymbolTable (I),
        # NumberOfSymbols (I), SizeOfOptionalHeader (H), Characteristics (H)
        coff_fmt = "<HHIIIHH"
        coff_bytes = f.read(struct.calcsize(coff_fmt))
        if len(coff_bytes) < struct.calcsize(coff_fmt):
            self.details = {"error": "Truncated COFF header"}
            return

        machine, num_sections, timedate, ptr_sym, num_sym, opt_hdr_size, characteristics = struct.unpack(
            coff_fmt, coff_bytes
        )

        machine_name = PE_MACHINE_MAP.get(machine, f"Unknown ({hex(machine)})")
        is_arm64ec = (machine == IMAGE_FILE_MACHINE_ARM64EC)
        is_arm64 = (machine == IMAGE_FILE_MACHINE_ARM64)
        is_x64 = (machine == IMAGE_FILE_MACHINE_AMD64)

        opt_magic_str = "None"
        subsystem = 0
        if opt_hdr_size > 0:
            opt_magic_bytes = f.read(2)
            if len(opt_magic_bytes) == 2:
                opt_magic = struct.unpack("<H", opt_magic_bytes)[0]
                if opt_magic == 0x10b:
                    opt_magic_str = "PE32 (32-bit)"
                elif opt_magic == 0x20b:
                    opt_magic_str = "PE32+ (64-bit)"
                else:
                    opt_magic_str = f"Magic({hex(opt_magic)})"

                # Subsystem is at offset 68 in PE32+ (or offset 68 in PE32)
                f.seek(e_lfanew + 4 + struct.calcsize(coff_fmt) + 68)
                sub_bytes = f.read(2)
                if len(sub_bytes) == 2:
                    subsystem = struct.unpack("<H", sub_bytes)[0]

        subsystem_str = "IMAGE_SUBSYSTEM_WINDOWS_CUI (Console)" if subsystem == 3 else (
            "IMAGE_SUBSYSTEM_WINDOWS_GUI (GUI)" if subsystem == 2 else f"Subsystem({subsystem})"
        )

        self.details = {
            "machine": machine_name,
            "machine_id": hex(machine),
            "opt_header_magic": opt_magic_str,
            "subsystem": subsystem_str,
            "is_arm64ec": is_arm64ec,
            "is_arm64": is_arm64,
            "is_x64": is_x64,
            "num_sections": num_sections,
            "characteristics": hex(characteristics),
        }


def audit_directory(root_dir: str) -> List[Dict[str, Any]]:
    results = []
    for root, _, files in os.walk(root_dir):
        for file in files:
            full_path = os.path.join(root, file)
            # Only audit regular files
            if os.path.islink(full_path) or not os.path.isfile(full_path):
                continue
            try:
                with open(full_path, "rb") as f:
                    magic = f.read(4)
                if magic == b"\x7fELF" or magic[:2] == b"MZ":
                    auditor = BinaryAuditor(full_path)
                    res = auditor.audit()
                    results.append(res)
            except Exception as e:
                results.append({"path": full_path, "error": str(e)})
    return results


def main():
    parser = argparse.ArgumentParser(description="Audit ELF and PE binaries in Proton package.")
    parser.add_argument("path", help="Path to single binary or directory of Proton package")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    parser.add_argument("--out", help="Write report to output file")

    args = parser.parse_args()

    if not os.path.exists(args.path):
        print(f"Error: Path {args.path} does not exist.", file=sys.stderr)
        sys.exit(1)

    if os.path.isdir(args.path):
        results = audit_directory(args.path)
    else:
        auditor = BinaryAuditor(args.path)
        results = [auditor.audit()]

    if args.json or args.out and args.out.endswith(".json"):
        output_str = json.dumps(results, indent=2)
    else:
        # Formatted text table
        lines = []
        lines.append(f"{'Filename':<35} | {'Format':<6} | {'Machine/Arch':<25} | {'Type/Subsystem':<20} | {'Interpreter / Note'}")
        lines.append("-" * 120)
        for r in results:
            if "error" in r and "details" not in r:
                lines.append(f"{r['path']:<35} | ERROR: {r['error']}")
                continue
            fn = r['filename']
            fmt = r['format']
            det = r['details']
            mach = det.get('machine', 'N/A')
            t = det.get('type') or det.get('subsystem', 'N/A')
            interp = det.get('pt_interp', '')
            if not interp and det.get('is_arm64ec'):
                interp = "[ARM64EC FEX Module]"
            lines.append(f"{fn:<35} | {fmt:<6} | {mach:<25} | {t:<20} | {interp}")
        output_str = "\n".join(lines)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(output_str)
        print(f"Report written to {args.out}")
    else:
        print(output_str)


if __name__ == "__main__":
    main()
