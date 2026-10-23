"""Tests for the simplified Italian payroll rules (hand-computed expected values)."""
import unittest
from decimal import Decimal as D

import payroll_rules as pr


def employee(**kw):
    base = {
        'employee_id': 'E999', 'hire_date': '2015-01-01', 'termination_date': None,
        'contract': {'monthly_gross': 2600.00},
        'opening_balances': {'leave_days': 0.0, 'tfr_fund': 0.00},
    }
    base.update(kw)
    return base


def month_row(month, **kw):
    row = {'month': month, 'overtime_hours': 0.0, 'holiday_work': [], 'sick_episodes': [], 'leave_days_taken': 0.0}
    row.update(kw)
    return row


def line(payslip, code):
    found = [l for l in payslip['lines'] if l['code'] == code]
    return D(str(found[0]['amount'])) if found else None


class SingleItems(unittest.TestCase):
    def test_overtime_is_paid_with_25_percent_premium(self):
        # 2400 / 173 = 13.8728 per hour; 10 h x 1.25 = 173.41
        self.assertEqual(pr.overtime_pay(D('2400'), D('10')), D('173.41'))

    def test_base_pay_is_prorated_on_calendar_days(self):
        # terminated on 15 March: 2000 x 15 / 31 = 967.74
        self.assertEqual(pr.base_pay(D('2000'), 15, 31), D('967.74'))

    def test_sick_days_after_the_third_are_reduced_by_25_percent(self):
        # daily rate 2600 / 26 = 100; 5-day episode -> 2 days x 100 x 0.25 = -50.00
        self.assertEqual(pr.sick_adjustment(D('2600'), [5]), D('-50.00'))

    def test_short_sick_episode_has_no_reduction(self):
        self.assertEqual(pr.sick_adjustment(D('2600'), [3, 2]), D('0.00'))

    def test_holiday_work_is_paid_with_50_percent_premium(self):
        # 1730 / 173 = 10 per hour; 8 h x 1.5 = 120.00
        self.assertEqual(pr.holiday_work_pay(D('1730'), D('8')), D('120.00'))

    def test_only_25_april_falls_on_a_rest_day_in_h1_2026(self):
        self.assertEqual(pr.rest_day_holidays('2026-04', '2026-04-01', '2026-04-30'), ['2026-04-25'])
        self.assertEqual(pr.rest_day_holidays('2026-04', '2026-04-01', '2026-04-20'), [])
        self.assertEqual(pr.rest_day_holidays('2026-05', '2026-05-01', '2026-05-31'), [])

    def test_days_employed_follow_hire_and_termination_dates(self):
        self.assertEqual(pr.days_employed(employee(hire_date='2026-02-16'), '2026-02'), 13)
        self.assertEqual(pr.days_employed(employee(termination_date='2026-03-15'), '2026-03'), 15)
        self.assertEqual(pr.days_employed(employee(termination_date='2026-03-15'), '2026-04'), 0)
        self.assertEqual(pr.days_employed(employee(), '2026-01'), 31)


class Totals(unittest.TestCase):
    def test_inps_irpef_and_net_pay(self):
        lines = [{'code': 'BASE', 'amount': 2400.00}, {'code': 'STR', 'amount': 173.41}]
        t = pr.totals(lines)
        self.assertEqual(D(str(t['gross'])), D('2573.41'))
        self.assertEqual(D(str(t['inps_employee'])), D('236.50'))   # 9.19 %
        self.assertEqual(D(str(t['irpef'])), D('537.49'))           # 23 % of (gross - INPS), simplified
        self.assertEqual(D(str(t['net_pay'])), D('1799.42'))

    def test_tfr_is_paid_on_top_of_net_and_is_not_taxed(self):
        lines = [{'code': 'BASE', 'amount': 1000.00}, {'code': 'TFR', 'amount': 500.00}]
        t = pr.totals(lines)
        self.assertEqual(D(str(t['gross'])), D('1000.00'))
        self.assertEqual(D(str(t['tfr'])), D('500.00'))
        # 1000 - 91.90 - 208.86 + 500
        self.assertEqual(D(str(t['net_pay'])), D('1199.24'))


class ComputePayslip(unittest.TestCase):
    def test_regular_month_has_base_and_overtime_lines(self):
        p = pr.compute_payslip(employee(contract={'monthly_gross': 2400.00}),
                               [month_row('2026-01', overtime_hours=10.0)])
        self.assertEqual(line(p, 'BASE'), D('2400.00'))
        self.assertEqual(line(p, 'STR'), D('173.41'))
        self.assertIsNone(line(p, 'FEST'))
        self.assertEqual(D(str(p['totals']['net_pay'])), D('1799.42'))

    def test_april_pays_the_saturday_holiday(self):
        p = pr.compute_payslip(employee(), [month_row('2026-04')])
        self.assertEqual(line(p, 'FEST'), D('100.00'))

    def test_holiday_work_and_sick_lines(self):
        p = pr.compute_payslip(employee(), [month_row(
            '2026-05', holiday_work=[{'date': '2026-05-01', 'hours': 8.0}],
            sick_episodes=[{'start': '2026-05-11', 'days': 5}])])
        # 2600 / 173 = 15.0289; 8 h x 1.5 = 180.35
        self.assertEqual(line(p, 'FESTLAV'), D('180.35'))
        self.assertEqual(line(p, 'MAL'), D('-50.00'))

    def test_termination_month_pays_13th_leave_and_tfr(self):
        emp = employee(termination_date='2026-03-15',
                       opening_balances={'leave_days': 5.0, 'tfr_fund': 10000.00})
        rows = [month_row('2026-01', leave_days_taken=2.0), month_row('2026-02'),
                month_row('2026-03', leave_days_taken=1.0)]
        p = pr.compute_payslip(emp, rows)
        self.assertEqual(line(p, 'BASE'), D('1258.06'))       # 2600 x 15 / 31
        self.assertEqual(line(p, 'RAT13'), D('650.00'))       # 3 months (Mar has 15 days) x 2600 / 12
        self.assertEqual(line(p, 'FERIE'), D('850.00'))       # (5 + 26/12 x 3 - 3) = 8.5 days x 100
        self.assertEqual(line(p, 'TFR'), D('10478.37'))       # 10000 + (2600 + 2600 + 1258.06) / 13.5

    def test_hire_month_with_less_than_15_days_does_not_accrue(self):
        emp = employee(hire_date='2026-02-16', termination_date='2026-03-31')
        rows = [month_row('2026-02'), month_row('2026-03')]
        p = pr.compute_payslip(emp, rows)
        self.assertEqual(line(p, 'RAT13'), D('216.67'))       # only March counts: 2600 / 12


if __name__ == '__main__':
    unittest.main()
