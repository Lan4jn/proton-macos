import json
import hashlib
from pathlib import Path

LAB = Path("/Users/mewcapoo/Projects/proton-macos-lab")

def main():
    out_dir = LAB / "logs/wine-commit-pin"
    out_dir.mkdir(parents=True, exist_ok=True)

    evidence = {
        "metadata": {
            "task": "task-126",
            "title": "Generator Counting and Structural Equivalence Wine Commit Pinning",
            "author": "x64-pipe-reviewer",
            "date": "2026-10-24T02:30:00Z",
            "status": "verified"
        },
        "acceptance_1_version_semantics": {
            "version_file_content": "1790245028 experimental-11.0-20260924-arm64",
            "makefile_in_definition": "all-dist:\n\techo \`date '+%s'\` \`GIT_DIR=$(abspath $(SRCDIR)/.git) git describe --tags\` > $(DIST_VERSION)",
            "source_location": "ValveSoftware/Proton Makefile.in:1493",
            "first_field_semantic": "Unix POSIX epoch timestamp of the exact moment 'make all-dist' executed the build container command (1790245028 = 2026-09-24T10:17:08Z).",
            "second_field_semantic": "Proton repository git describe tag ('experimental-11.0-20260924-arm64').",
            "why_timestamp_head_inference_failed": [
                "Commit 3c1a3fef was committed at 2026-09-24T23:32:35Z (author 22:17:15Z), which is 12 hours AFTER the container build execution timestamp 10:17:08Z.",
                "A build running at 10:17:08Z cannot contain commits from 23:32:35Z.",
                "Proton pins submodules via gitlinks rather than live tracking HEAD at the second of build."
            ]
        },
        "acceptance_2_candidate_comparison_matrix": [
            {
                "commit": "dc26e61847081a1b5cb0733dc30feba6ee575482",
                "repo": "https://github.com/ValveSoftware/wine",
                "branch": "proton_11.0 / experimental_11.0",
                "date": "2026-08-03T16:08:00Z",
                "author": "ivyl",
                "subject": "winebus: Fix initial axis values for evdev gamepads.",
                "checks": {
                    "vk_xml_version_1_4_357": False,
                    "vk_xml_version_actual": "1.4.339",
                    "all_vk_instance_funcs_count_82": False,
                    "all_vk_instance_funcs_count_actual": 79,
                    "contains_3_arm_functions": False,
                    "arm_functions_found": 0,
                    "sizeof_vulkan_instance_0x2f8": False,
                    "sizeof_vulkan_instance_actual": "0x2e0 (736)"
                },
                "verdict": "FAIL",
                "reason": "Outdated Vulkan spec 1.4.339, missing 3 ARM instance extension functions (differs by 24 bytes)."
            },
            {
                "commit": "20d85e6200bd9ce2a6b22106725287f32f48651c",
                "repo": "https://github.com/ValveSoftware/wine",
                "branch": "experimental_11.0",
                "date": "2026-09-01T08:09:04Z",
                "author": "Georg Lehmann",
                "subject": "winevulkan: Update to VK spec version 1.4.357.",
                "checks": {
                    "vk_xml_version_1_4_357": True,
                    "vk_xml_version_actual": "1.4.357",
                    "all_vk_instance_funcs_count_82": True,
                    "all_vk_instance_funcs_count_actual": 82,
                    "contains_3_arm_functions": True,
                    "arm_functions_found": 3,
                    "sizeof_vulkan_instance_0x2f8": False,
                    "sizeof_vulkan_instance_actual": "0x2f0 (752)"
                },
                "verdict": "FAIL",
                "reason": "Has 82 functions and 1.4.357, but misses api_version in struct vulkan_instance (sizeof=0x2f0 instead of shipped 0x2f8)."
            },
            {
                "commit": "66ee546cbea4f15d9098bc146312a818c356f9e5",
                "repo": "https://github.com/ValveSoftware/wine",
                "branch": "experimental_11.0",
                "date": "2026-09-12T01:11:21Z",
                "author": "Paul Gofman",
                "subject": "win32u: Support d3d12 fence timelines.",
                "checks": {
                    "vk_xml_version_1_4_357": True,
                    "vk_xml_version_actual": "1.4.357",
                    "all_vk_instance_funcs_count_82": True,
                    "all_vk_instance_funcs_count_actual": 82,
                    "contains_3_arm_functions": True,
                    "arm_functions_found": 3,
                    "sizeof_vulkan_instance_0x2f8": True,
                    "sizeof_vulkan_instance_actual": "0x2f8 (760)"
                },
                "verdict": "PASS (Range Start)",
                "reason": "First commit that brings struct vulkan_instance to 0x2f8 (via uint32_t api_version) with 82 functions and 1.4.357."
            },
            {
                "commit": "1c78596625336a73dbfc035dbbcf0dbdd95b06eb",
                "repo": "https://github.com/ValveSoftware/wine",
                "branch": "experimental_11.0",
                "date": "2026-09-22T19:35:48Z",
                "author": "Paul Gofman",
                "subject": "fixup! winevulkan: Introduce Wine-specific VR extensions.",
                "checks": {
                    "vk_xml_version_1_4_357": True,
                    "vk_xml_version_actual": "1.4.357",
                    "all_vk_instance_funcs_count_82": True,
                    "all_vk_instance_funcs_count_actual": 82,
                    "contains_3_arm_functions": True,
                    "arm_functions_found": 3,
                    "sizeof_vulkan_instance_0x2f8": True,
                    "sizeof_vulkan_instance_actual": "0x2f8 (760)"
                },
                "verdict": "PASS (Intermediate in Equivalence Range)",
                "reason": "Last Vulkan-touching commit before the 2026-09-24 build timestamp."
            },
            {
                "commit": "adea6cbac9d00bb22910145354d00c463fcf3afc",
                "repo": "https://github.com/ValveSoftware/wine",
                "branch": "experimental_11.0",
                "date": "2026-09-24T00:51:45Z",
                "author": "Alistair Leslie-Hughes",
                "committer": "Paul Gofman",
                "subject": "uiautomationcore: Add UiaDisconnectAllProviders stub.",
                "checks": {
                    "vk_xml_version_1_4_357": True,
                    "vk_xml_version_actual": "1.4.357",
                    "all_vk_instance_funcs_count_82": True,
                    "all_vk_instance_funcs_count_actual": 82,
                    "contains_3_arm_functions": True,
                    "arm_functions_found": 3,
                    "sizeof_vulkan_instance_0x2f8": True,
                    "sizeof_vulkan_instance_actual": "0x2f8 (760)"
                },
                "verdict": "PASS (Recommended Final HEAD Candidate)",
                "reason": "Latest commit on ValveSoftware/wine experimental_11.0 preceding build timestamp 2026-09-24T10:17:08Z. Perfectly satisfies 82 functions, 1.4.357, and 0x2f8 size."
            }
        ],
        "acceptance_3_structural_equivalence_range": {
            "range_start": {
                "commit": "66ee546cbea4f15d9098bc146312a818c356f9e5",
                "date": "2026-09-12T01:11:21Z",
                "subject": "win32u: Support d3d12 fence timelines."
            },
            "range_end": {
                "commit": "adea6cbac9d00bb22910145354d00c463fcf3afc",
                "date": "2026-09-24T00:51:45Z",
                "subject": "uiautomationcore: Add UiaDisconnectAllProviders stub."
            },
            "equivalence_properties": [
                "VK_XML_VERSION is invariant at 1.4.357 across the range.",
                "ALL_VK_INSTANCE_FUNCS count is invariant at 82 across the range.",
                "The 3 ARM instance extension functions are invariant across the range.",
                "sizeof(struct vulkan_instance) is invariant at 0x2f8 (760 bytes).",
                "physical_devices offset is invariant at 0x2e0 (736 bytes).",
                "physical_device_count offset is invariant at 0x2e8 (744 bytes).",
                "sizeof(struct vulkan_physical_device) is invariant at 0x288 (648 bytes)."
            ],
            "recommended_unique_candidate": "adea6cbac9d00bb22910145354d00c463fcf3afc (pre-build latest HEAD)"
        },
        "acceptance_4_falsification_criteria": {
            "criteria": [
                "If building a candidate commit produces sizeof(struct vulkan_instance) != 0x2f8 (760), it is refuted.",
                "If building produces physical_devices offset != 0x2e0 (736), it is refuted.",
                "If building produces physical_device_count offset != 0x2e8 (744), it is refuted.",
                "If building produces sizeof(struct vulkan_physical_device) != 0x288 (648), it is refuted.",
                "If ALL_VK_INSTANCE_FUNCS does not equal 82, it is refuted."
            ]
        },
        "acceptance_6_three_layer_conclusion": {
            "layer_1_shipped_specs": {
                "api_version": "1.4.357",
                "instance_funcs": 82,
                "sizeof_vulkan_instance": "0x2f8",
                "offset_physical_devices": "0x2e0",
                "offset_physical_device_count": "0x2e8",
                "sizeof_vulkan_physical_device": "0x288"
            },
            "layer_2_candidate_classification": {
                "structural_equivalence_range": "66ee546cbea4 .. adea6cbac9d0",
                "recommended_latest_head": "adea6cbac9d00bb22910145354d00c463fcf3afc"
            },
            "layer_3_unverified_aspects": [
                "Exact byte-level SHA identity of compiled binaries requires complete toolchain replication (SteamRT SDK arm64-llvm 4.0.20260714.251823-0).",
                "Any out-of-tree patch applied by Valve during container packaging not committed to git."
            ]
        }
    }

    evidence_file = out_dir / "commit-pin-evidence.json"
    evidence_file.write_text(json.dumps(evidence, indent=2) + "\n")
    print(f"Successfully wrote {evidence_file}")

if __name__ == "__main__":
    main()
