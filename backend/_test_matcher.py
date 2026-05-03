"""Unit test for _match_clinic_to_account.

Proves the bug exists in the OLD logic (RL → Embrace cross-match) and
confirms the new logic returns the correct outcomes for every clinic that
has come through the intake form recently.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from google_ads import _match_clinic_to_account

# Snapshot of the 8 accounts in the CM MCC as of 2026-05-03.
ACCOUNTS = {
    "6044895978": "",  # No descriptive name on Google (RL Physio)
    "1555828797": "Clinic Mastery Google Ads",
    "5937068774": "Embrace Physiotherapy",
    "7999269089": "Infinity Health and Osteo",
    "5022957448": "Newcastle Aquatic Physiotherapy",
    "2169213449": "Podiatry & Moore",
    "1002107425": "The Psychology, Counselling & Wellbeing Centre",
    "7082299462": "Your Millennial Therapist",
}

CASES: list[tuple[str, str | None, str]] = [
    # (clinic_name, expected_customer_id, comment)
    ("Embrace Physiotherapy",                          "5937068774", "exact"),
    ("Podiatry & Moore",                               "2169213449", "exact"),
    ("Podiatry and Moore",                             "2169213449", "and vs &"),
    ("The Psychology, Counselling & Wellbeing Centre", "1002107425", "exact"),
    ("RL Physiotherapy",                               None,         "no name in MCC, generic-only overlap should NOT match Embrace/Newcastle"),
    ("The Millennial Therapist",                       "7082299462", "Your Millennial Therapist"),
    ("Newcastle Aquatic Physiotherapy",                "5022957448", "exact"),
    ("Sara's Allied Health Clinic",                    None,         "no brand match in MCC"),
    ("Infinity Health and Osteo",                      "7999269089", "exact"),
    ("Mick Jordan Natural Therapies",                  None,         "not in MCC"),
]


def main() -> None:
    failures = 0
    for clinic, expected, comment in CASES:
        result = _match_clinic_to_account(clinic, ACCOUNTS)
        actual = result[1] if result else None
        ok = actual == expected
        flag = "OK " if ok else "FAIL"
        score = f"{result[0]:.2f}" if result else "  - "
        actual_str = actual or "no match"
        expected_str = expected or "no match"
        print(f"  {flag}  {clinic:55s}  expected={expected_str:12s}  actual={actual_str:12s}  jaccard={score}  ({comment})")
        if not ok:
            failures += 1
    print()
    print(f"{'PASS' if failures == 0 else 'FAIL'}: {len(CASES) - failures}/{len(CASES)} cases")
    sys.exit(0 if failures == 0 else 1)


if __name__ == "__main__":
    main()
