"""Run every test script in this folder and report pass/fail.

Run: python3 src/tests/run_all.py
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = [
    "test_unit_framing_protocol.py",
    "test_fsm_simulation.py",
    "test_integration_sockets.py",
]

failed = []
for name in TESTS:
    print(f"\n===== {name} =====", flush=True)
    rc = subprocess.call([sys.executable, os.path.join(HERE, name)], timeout=120)
    if rc != 0:
        failed.append(name)

print("\n===== summary =====")
for name in TESTS:
    print(("FAIL " if name in failed else "PASS ") + name)
sys.exit(1 if failed else 0)
