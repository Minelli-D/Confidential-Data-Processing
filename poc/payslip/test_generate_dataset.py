"""Tests for the synthetic dataset generator and its answer key."""
import json
import unittest
from collections import Counter

import generate_dataset as gd
import reconcile as rc

DATASET, ANSWER_KEY = gd.generate(seed=gd.DEFAULT_SEED)


class Shape(unittest.TestCase):
    def test_100_synthetic_employees_over_the_first_semester_2026(self):
        meta = DATASET['dataset']
        self.assertTrue(meta['synthetic'])
        self.assertEqual((meta['period']['from'], meta['period']['to'], meta['currency']), ('2026-01', '2026-06', 'EUR'))
        self.assertEqual(len(DATASET['employees']), 100)

    def test_one_payslip_per_employee_per_month_employed(self):
        months = Counter(p['employee_id'] for p in DATASET['payslips'])
        self.assertEqual(len(DATASET['payslips']), len(DATASET['attendance']))
        self.assertEqual(max(months.values()), 6)
        self.assertGreater(len(DATASET['payslips']), 550)

    def test_edge_cases_are_present(self):
        emps = DATASET['employees']
        self.assertGreaterEqual(sum(1 for e in emps if e['termination_date']), 4)
        self.assertGreaterEqual(sum(1 for e in emps if e['hire_date'] >= '2026-01-01'), 3)
        self.assertTrue(any(ep['days'] > 3 for r in DATASET['attendance'] for ep in r['sick_episodes']))
        self.assertTrue(any(r['holiday_work'] for r in DATASET['attendance']))
        self.assertTrue(any(r['overtime_hours'] for r in DATASET['attendance']))

    def test_attendance_adds_up(self):
        for r in DATASET['attendance']:
            sick = sum(ep['days'] for ep in r['sick_episodes'])
            self.assertEqual(r['days_worked'], r['working_days'] - sick - r['leave_days_taken'], r)
            self.assertGreaterEqual(r['days_worked'], 0, r)

    def test_same_seed_gives_the_same_files(self):
        again, key_again = gd.generate(seed=gd.DEFAULT_SEED)
        self.assertEqual(json.dumps(again, sort_keys=True), json.dumps(DATASET, sort_keys=True))
        self.assertEqual(json.dumps(key_again, sort_keys=True), json.dumps(ANSWER_KEY, sort_keys=True))


class PlantedErrors(unittest.TestCase):
    def test_about_five_percent_of_payslips_have_one_planted_error(self):
        planted = ANSWER_KEY['planted_errors']
        share = len(planted) / len(DATASET['payslips'])
        self.assertTrue(0.04 <= share <= 0.06, share)
        self.assertEqual(len({p['payslip_id'] for p in planted}), len(planted))

    def test_every_error_type_is_used(self):
        self.assertEqual({p['error_type'] for p in ANSWER_KEY['planted_errors']}, set(gd.ERROR_TYPES))

    def test_reconciliation_finds_exactly_the_planted_errors(self):
        report = rc.reconcile(DATASET)
        s = rc.score(report['findings'], ANSWER_KEY['planted_errors'])
        self.assertEqual((s['missed'], s['unexpected']), ([], []))
        self.assertEqual(s['matched'], len(ANSWER_KEY['planted_errors']))

    def test_answer_key_amounts_match_the_findings(self):
        found = {(f['payslip_id'], f['line']): f for f in rc.reconcile(DATASET)['findings']}
        for p in ANSWER_KEY['planted_errors']:
            f = found[(p['payslip_id'], p['line'])]
            self.assertEqual((f['expected'], f['issued']), (p['expected_amount'], p['issued_amount']), p)


if __name__ == '__main__':
    unittest.main()
