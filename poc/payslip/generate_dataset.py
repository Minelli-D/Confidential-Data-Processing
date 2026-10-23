"""Generates the SYNTHETIC payslip reconciliation dataset (100 employees, January-June 2026).

Writes two files:
    payslips-2026-H1.json    employees, monthly attendance and the issued payslips (with planted errors)
    answer-key-2026-H1.json  the planted errors: never give this file to the enclave

    python3 generate_dataset.py --out-dir ../../data
"""
import argparse
import copy
import json
import os
import random
from datetime import date, timedelta

import payroll_rules as pr

DEFAULT_SEED = 20260101
MONTHS = ['2026-01', '2026-02', '2026-03', '2026-04', '2026-05', '2026-06']
EMPLOYEES = 100
TERMINATIONS = 6
HIRES = 4
ERROR_SHARE = 0.05

ERROR_TYPES = {
    'OVERTIME_NO_PREMIUM': 'Overtime paid at the plain hourly rate, without the +25% premium',
    'OVERTIME_HOURS_SHORT': 'Overtime paid for 2 hours fewer than the hours recorded',
    'HOLIDAY_REST_DAY_MISSING': '25 April 2026 (a Saturday) not paid as an extra day',
    'HOLIDAY_WORK_LOW_PREMIUM': 'Holiday work paid at +25% instead of +50%',
    'SICK_REDUCTION_MISSING': 'Sick days from the 4th paid at 100% instead of 75%',
    'TERMINATION_LEAVE_MISSING': 'Unused leave not paid in the termination month',
    'BASE_NOT_PRORATED': 'Full monthly salary paid in a partial month (hire or termination)',
}

FIRST_NAMES = ['Alessandro', 'Andrea', 'Anna', 'Beatrice', 'Chiara', 'Claudio', 'Daniela', 'Davide', 'Elena',
               'Elisa', 'Emanuele', 'Federica', 'Francesca', 'Francesco', 'Gabriele', 'Giada', 'Giorgia',
               'Giovanni', 'Giulia', 'Ilaria', 'Laura', 'Leonardo', 'Lorenzo', 'Luca', 'Marco', 'Maria',
               'Martina', 'Matteo', 'Michela', 'Nicola', 'Paola', 'Paolo', 'Riccardo', 'Roberta', 'Roberto',
               'Sara', 'Silvia', 'Simone', 'Stefano', 'Valentina']
LAST_NAMES = ['Barbieri', 'Bellini', 'Benedetti', 'Bianchi', 'Bruno', 'Caruso', 'Colombo', 'Conti', 'Costa',
              'De Luca', 'Esposito', 'Fabbri', 'Fontana', 'Gallo', 'Gatti', 'Giordano', 'Greco', 'Leone',
              'Lombardi', 'Mancini', 'Marchetti', 'Marini', 'Martinelli', 'Mariani', 'Moretti', 'Pellegrini',
              'Ricci', 'Rinaldi', 'Rizzo', 'Romano', 'Rossi', 'Russo', 'Santoro', 'Serra', 'Testa', 'Valentini',
              'Vitale', 'Villa', 'Ferrari', 'Ferri']
DEPARTMENTS = ['Amministrazione', 'Vendite', 'Magazzino', 'IT', 'Produzione', 'Risorse umane']
LEVELS = {'L1': (3200, 3800), 'L2': (2700, 3200), 'L3': (2300, 2700), 'L4': (2000, 2300), 'L5': (1850, 2000),
          'L6': (1700, 1850)}
TERMINATION_REASONS = ['dimissioni', 'licenziamento', 'fine contratto a termine']


def _date_between(rng, start, end):
    return start + timedelta(days=rng.randint(0, (end - start).days))


def _employees(rng):
    names = rng.sample([(f, l) for f in FIRST_NAMES for l in LAST_NAMES], EMPLOYEES)
    ids = [f'E{i:03d}' for i in range(1, EMPLOYEES + 1)]
    leavers = set(rng.sample(ids, TERMINATIONS))
    joiners = set(rng.sample([i for i in ids if i not in leavers], HIRES))
    employees = []
    for eid, (first, last) in zip(ids, names):
        level = rng.choices(list(LEVELS), weights=[1, 2, 4, 6, 5, 3])[0]
        lo, hi = LEVELS[level]
        gross = round(rng.uniform(lo, hi), 2)
        if eid in joiners:
            hire = date(2026, rng.randint(2, 5), rng.randint(2, 20))
            opening = {'leave_days': 0.0, 'tfr_fund': 0.0}
        else:
            hire = _date_between(rng, date(2008, 1, 1), date(2025, 9, 30))
            years = (date(2026, 1, 1) - hire).days / 365.25
            opening = {'leave_days': rng.randint(0, 30) / 2,
                       'tfr_fund': round(gross * 13 / 13.5 * years * rng.uniform(0.6, 1.0), 2)}
        termination = date(2026, rng.randint(2, 6), rng.randint(5, 25)) if eid in leavers else None
        employees.append({
            'employee_id': eid, 'first_name': first, 'last_name': last,
            'department': rng.choice(DEPARTMENTS),
            'hire_date': hire.isoformat(),
            'termination_date': termination.isoformat() if termination else None,
            'termination_reason': rng.choice(TERMINATION_REASONS) if termination else None,
            'contract': {'ccnl': 'Commercio (semplificato)', 'level': level,
                         'contract_type': 'tempo determinato' if rng.random() < 0.15 else 'tempo indeterminato',
                         'weekly_hours': 40, 'monthly_gross': gross},
            'opening_balances': opening,
        })
    return employees


def _working_days(start, end):
    days, d = [], start
    while d <= end:
        if d.weekday() < 5 and d.isoformat() not in pr.PUBLIC_HOLIDAYS:
            days.append(d)
        d += timedelta(days=1)
    return days


def _attendance(rng, emp):
    rows, leave_taken, accrued = [], 0.0, 0
    for month in MONTHS:
        if pr.days_employed(emp, month) == 0:
            continue
        start, end = pr._employment_window(emp, month)
        work_days = _working_days(start, end)
        if pr.days_employed(emp, month) >= pr.ACCRUAL_MIN_DAYS:
            accrued += 1
        free = len(work_days)

        sick = []
        if rng.random() < 0.15 and free > 2:
            days = min(rng.choices([1, 2, 3, 4, 5, 6, 8], weights=[3, 4, 3, 3, 3, 2, 2])[0], free - 1)
            sick.append({'start': rng.choice(work_days[:len(work_days) - days + 1]).isoformat(), 'days': days})
            free -= days
        available = int(emp['opening_balances']['leave_days'] + 26 / 12 * accrued - leave_taken)
        leave = min(rng.choices([0, 1, 2, 3, 5, 8], weights=[10, 3, 3, 2, 2, 1])[0], max(0, available), free)
        leave_taken += leave

        holiday_work = []
        if emp['department'] in ('Vendite', 'Magazzino'):
            for h in pr.PUBLIC_HOLIDAYS:
                if h.startswith(month) and start.isoformat() <= h <= end.isoformat() \
                        and date.fromisoformat(h).weekday() < 5 and rng.random() < 0.3:
                    holiday_work.append({'date': h, 'hours': rng.choice([4.0, 8.0])})

        rows.append({
            'employee_id': emp['employee_id'], 'month': month,
            'working_days': len(work_days), 'days_worked': len(work_days) - sum(s['days'] for s in sick) - leave,
            'overtime_hours': rng.randint(4, 40) / 2 if rng.random() < 0.35 else 0.0,
            'holiday_work': holiday_work, 'sick_episodes': sick, 'leave_days_taken': float(leave),
        })
    return rows


def _payslips(employees, attendance):
    payslips = []
    for emp in employees:
        rows = [r for r in attendance if r['employee_id'] == emp['employee_id']]
        for i, row in enumerate(rows):
            p = pr.compute_payslip(emp, rows[:i + 1])
            payslips.append({'payslip_id': f"PS-{row['month']}-{emp['employee_id']}",
                             'employee_id': emp['employee_id'], 'month': row['month'],
                             'pay_date': f"{row['month']}-27", **p})
    return payslips


def _eligible(error_type, payslip, emp):
    lines = {l['code']: l for l in payslip['lines']}
    return {
        'OVERTIME_NO_PREMIUM': 'STR' in lines,
        'OVERTIME_HOURS_SHORT': 'STR' in lines and lines['STR']['quantity'] >= 3,
        'HOLIDAY_REST_DAY_MISSING': 'FEST' in lines,
        'HOLIDAY_WORK_LOW_PREMIUM': 'FESTLAV' in lines,
        'SICK_REDUCTION_MISSING': 'MAL' in lines,
        'TERMINATION_LEAVE_MISSING': 'FERIE' in lines,
        'BASE_NOT_PRORATED': pr.days_employed(emp, payslip['month']) < pr._month_bounds(payslip['month'])[1].day,
    }[error_type]


def _plant(error_type, payslip, emp):
    """Apply the error to the issued payslip. Returns the affected line code."""
    gross = emp['contract']['monthly_gross']
    lines = {l['code']: l for l in payslip['lines']}
    if error_type == 'OVERTIME_NO_PREMIUM':
        code = 'STR'
        lines[code]['amount'] = float(pr._cents(pr._d(lines[code]['quantity']) * pr.hourly_rate(gross)))
        lines[code]['rate'] = float(pr._cents(pr.hourly_rate(gross)))
    elif error_type == 'OVERTIME_HOURS_SHORT':
        code = 'STR'
        lines[code]['quantity'] -= 2
        lines[code]['amount'] = float(pr.overtime_pay(gross, lines[code]['quantity']))
    elif error_type == 'HOLIDAY_WORK_LOW_PREMIUM':
        code = 'FESTLAV'
        lines[code]['amount'] = float(pr._cents(pr._d(lines[code]['quantity']) * pr.hourly_rate(gross) * pr._d('1.25')))
        lines[code]['rate'] = float(pr._cents(pr.hourly_rate(gross) * pr._d('1.25')))
    elif error_type == 'BASE_NOT_PRORATED':
        code = 'BASE'
        lines[code]['quantity'] = pr._month_bounds(payslip['month'])[1].day
        lines[code]['amount'] = float(gross)
    else:
        code = {'HOLIDAY_REST_DAY_MISSING': 'FEST', 'SICK_REDUCTION_MISSING': 'MAL',
                'TERMINATION_LEAVE_MISSING': 'FERIE'}[error_type]
        payslip['lines'] = [l for l in payslip['lines'] if l['code'] != code]
    payslip['totals'] = pr.totals(payslip['lines'])
    return code


def _plant_errors(rng, employees, payslips):
    emps = {e['employee_id']: e for e in employees}
    target = round(len(payslips) * ERROR_SHARE)
    # one of each type first, rarest pools first, then fill up with random eligible types
    types = sorted(ERROR_TYPES, key=lambda t: sum(_eligible(t, p, emps[p['employee_id']]) for p in payslips))
    types += rng.choices(list(ERROR_TYPES), weights=[5, 3, 2, 2, 4, 1, 1], k=target * 3)
    used, planted = set(), []
    for error_type in types:
        if len(planted) == target:
            break
        pool = [p for p in payslips if p['payslip_id'] not in used and _eligible(error_type, p, emps[p['employee_id']])]
        if not pool:
            continue
        payslip = rng.choice(pool)
        before = copy.deepcopy(payslip)
        code = _plant(error_type, payslip, emps[payslip['employee_id']])
        amount = lambda p: next((l['amount'] for l in p['lines'] if l['code'] == code), 0.0)
        used.add(payslip['payslip_id'])
        planted.append({
            'payslip_id': payslip['payslip_id'], 'employee_id': payslip['employee_id'], 'month': payslip['month'],
            'error_type': error_type, 'explanation': ERROR_TYPES[error_type], 'line': code,
            'expected_amount': amount(before), 'issued_amount': amount(payslip),
            'difference': float(pr._d(amount(payslip)) - pr._d(amount(before))),
            'net_impact': float(pr._d(payslip['totals']['net_pay']) - pr._d(before['totals']['net_pay'])),
        })
    return sorted(planted, key=lambda p: p['payslip_id'])


def generate(seed=DEFAULT_SEED):
    rng = random.Random(seed)
    employees = _employees(rng)
    attendance = [row for emp in employees for row in _attendance(rng, emp)]
    payslips = _payslips(employees, attendance)
    planted = _plant_errors(rng, employees, payslips)
    dataset = {
        'dataset': {
            'id': 'payslip-reconciliation-2026-H1', 'synthetic': True,
            'description': 'SYNTHETIC payslip data for the confidential processing POC. No real person.',
            'period': {'from': MONTHS[0], 'to': MONTHS[-1]}, 'currency': 'EUR', 'country': 'IT',
            'rules_version': pr.RULES_VERSION, 'seed': seed,
        },
        'calendar': {'public_holidays': pr.PUBLIC_HOLIDAYS},
        'employees': employees,
        'attendance': attendance,
        'payslips': payslips,
    }
    by_type = {t: sum(1 for p in planted if p['error_type'] == t) for t in ERROR_TYPES}
    answer_key = {
        'dataset_id': dataset['dataset']['id'],
        'warning': 'Test oracle only. Never send this file to S3 or to the enclave.',
        'summary': {'payslips': len(payslips), 'planted_errors': len(planted), 'by_type': by_type},
        'planted_errors': planted,
    }
    return dataset, answer_key


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--out-dir', default=os.path.join(os.path.dirname(__file__), '..', '..', 'data'))
    ap.add_argument('--seed', type=int, default=DEFAULT_SEED)
    args = ap.parse_args()
    dataset, answer_key = generate(args.seed)
    os.makedirs(args.out_dir, exist_ok=True)
    for name, obj in (('payslips-2026-H1.json', dataset), ('answer-key-2026-H1.json', answer_key)):
        with open(os.path.join(args.out_dir, name), 'w') as f:
            json.dump(obj, f, indent=2, ensure_ascii=False)
            f.write('\n')
    s = answer_key['summary']
    print(f"{len(dataset['employees'])} employees, {s['payslips']} payslips, {s['planted_errors']} planted errors")


if __name__ == '__main__':
    main()
