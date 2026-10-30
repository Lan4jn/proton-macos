"""
scripts/runtime/safe_process.py

Thin adapter delegating to scripts.backend.process.run_isolated
with verified controlled supervisor lifecycle management.
"""

from scripts.backend.process import LAB, run_isolated

# Export run_safe_isolated as alias for compatibility
run_safe_isolated = run_isolated

__all__ = ["LAB", "run_safe_isolated", "run_isolated"]
