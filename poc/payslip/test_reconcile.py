"""Tests for Mode A: recompute each issued payslip and report line differences."""
import copy
import unittest

import payroll_rules as pr
import reconcile as rc


def dataset_with_one_payslip(month='2026-01', **row_kw):
    emp = {'employee_id': 'E001', 'hire_date': '2015-01-01', 'termination_date': None,
           'contract': {'monthly_gross': 2400.00}, 'opening_balances': {'leave_days': 0.0, 'tfr_fund': 0.0}}
    row = {'employee_id': 'E001', 'month': month, 'overtime_hours': 10.0, 'holiday_work': [],
           'sick_episodes': [], 'leave_days_taken': 0.0}
    row.update(row_kw)
    expected = pr.compute_payslip(emp, [row])
    payslip = {'payslip_id': f'PS-{month}-E001', 'employee_id': 'E001', 'month': month, **expected}
    return {'dataset': {'rules_version': pr.RULES_VERSION}, 'employees': [emp], 'attendance': [row],
            'payslips': [payslip]}


def set_line(payslip, code, amount):
    payslip['lines'] = [l for l in payslip['lines'] if l['code'] != code]
    if amount is not None:
        payslip['lines'].append({'code': code, 'amount': amount})
    payslip['totals'] = pr.totals(payslip['lines'])


class Reconcile(unittest.TestCase):
    def test_correct_payslip_has_no_findings(self):
        report = rc.reconcile(dataset_with_one_payslip())
        self.assertEqual(report['findings'], [])
        self.assertEqual(report['summary']['payslips_checked'], 1)

    def test_overtime_without_premium_is_reported(self):
        ds = dataset_with_one_payslip()
        set_line(ds['payslips'][0], 'STR', 138.73)
        [f] = rc.reconcile(ds)['findings']
        self.assertEqual((f['payslip_id'], f['line']), ('PS-2026-01-E001', 'STR'))
        self.assertEqual((f['expected'], f['issued'], f['difference']), (173.41, 138.73, -34.68))

    def test_missing_line_is_reported_as_issued_zero(self):
        ds = dataset_with_one_payslip(month='2026-04', overtime_hours=0.0)
        set_line(ds['payslips'][0], 'FEST', None)
        [f] = rc.reconcile(ds)['findings']
        # daily rate 2400 / 26 = 92.31
        self.assertEqual((f['line'], f['expected'], f['issued']), ('FEST', 92.31, 0.0))

    def test_net_impact_is_summed_in_the_summary(self):
        ds = dataset_with_one_payslip()
        set_line(ds['payslips'][0], 'STR', 138.73)
        summary = rc.reconcile(ds)['summary']
        self.assertEqual(summary['payslips_with_differences'], 1)
        expected_net = pr.compute_payslip(ds['employees'][0], ds['attendance'])['totals']['net_pay']
        self.assertEqual(summary['net_difference'], round(ds['payslips'][0]['totals']['net_pay'] - expected_net, 2))

    def test_dataset_for_other_rules_version_is_refused(self):
        ds = dataset_with_one_payslip()
        ds['dataset']['rules_version'] = 'it-simplified-9.9'
        with self.assertRaises(ValueError):
            rc.reconcile(ds)


class Score(unittest.TestCase):
    def test_score_counts_matched_missed_and_unexpected(self):
        findings = [{'payslip_id': 'P1', 'line': 'STR'}, {'payslip_id': 'P2', 'line': 'MAL'}]
        key = [{'payslip_id': 'P1', 'line': 'STR'}, {'payslip_id': 'P3', 'line': 'FERIE'}]
        s = rc.score(findings, key)
        self.assertEqual(s['matched'], 1)
        self.assertEqual(s['missed'], [{'payslip_id': 'P3', 'line': 'FERIE'}])
        self.assertEqual(s['unexpected'], [{'payslip_id': 'P2', 'line': 'MAL'}])


if __name__ == '__main__':
    unittest.main()
