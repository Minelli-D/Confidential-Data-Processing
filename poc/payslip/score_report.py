"""Test A on the laptop: compare the report produced by the enclave with the answer key.

    python3 score_report.py <report.json> [--answer-key ../../data/answer-key-2026-H1.json]

Exit code 0 only for a perfect score: every planted error found, nothing extra.
"""
import argparse
import json
import os
import sys

import reconcile as rc

DEFAULT_KEY = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data', 'answer-key-2026-H1.json')


def score_files(report_path, key_path):
    with open(report_path) as f:
        report = json.load(f)
    with open(key_path) as f:
        planted = json.load(f)['planted_errors']
    return rc.score(report['findings'], planted)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('report')
    ap.add_argument('--answer-key', default=DEFAULT_KEY)
    a = ap.parse_args(argv)
    s = score_files(a.report, a.answer_key)
    print(f"{s['matched']} matched, {len(s['missed'])} missed, {len(s['unexpected'])} unexpected")
    for label in ('missed', 'unexpected'):
        for item in s[label]:
            print(f"  {label}: {item['payslip_id']} line {item['line']}")
    return 0 if not s['missed'] and not s['unexpected'] else 1


if __name__ == '__main__':
    sys.exit(main())
