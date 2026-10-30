#!/usr/bin/env python3
"""
Unit tests for SteamCMD verification logic.
Tests semantic parsing and blocker pattern detection without hitting the network.
"""

import unittest
from verify_steamcmd_block import parse_steamcmd_output


class TestSteamCmdVerifier(unittest.TestCase):
    def test_parse_app_info_ownersonly(self):
        sample_output = """
        AppID : 4427310, change number : 39839235/39839235
        "4427310"
        {
            "common"
            {
                "name"          "Proton Experimental (ARM64)"
                "section_type"  "ownersonly"
                "type"          "Tool"
                "ReleaseState"  "released"
            }
        }
        """
        result = parse_steamcmd_output(sample_output)
        self.assertTrue(result["is_ownersonly"])
        self.assertEqual(result["app_name"], "Proton Experimental (ARM64)")

    def test_parse_anonymous_blocker(self):
        sample_output = """
        Connecting anonymously to Steam Public...OK
        Waiting for client config...OK
        Waiting for user info...OK
        Not for anonymous users.
        ERROR! Failed to install app '4427310' (No subscription)
        Unloading Steam API...OK
        """
        result = parse_steamcmd_output(sample_output)
        self.assertTrue(result["is_anonymous_blocked"])
        self.assertTrue(result["has_no_subscription"])
        self.assertTrue(any("Not for anonymous users" in l for l in result["error_lines"]))

    def test_parse_clean_output_not_blocked(self):
        sample_output = """
        Connecting anonymously to Steam Public...OK
        Success! App '4427310' fully installed.
        """
        result = parse_steamcmd_output(sample_output)
        self.assertFalse(result["is_anonymous_blocked"])
        self.assertFalse(result["has_no_subscription"])


if __name__ == "__main__":
    unittest.main()
