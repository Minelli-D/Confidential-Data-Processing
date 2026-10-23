"""Simplified Italian payroll rules for the payslip reconciliation POC.

These are the formulas that will run inside the enclave. They are deliberately
simplified (not exact to any CCNL) and pure: no I/O, no network, no clock.
Money is computed with Decimal and rounded half-up to the cent on every line.
"""
import calendar
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

RULES_VERSION = 'it-simplified-0.1'

HOURLY_DIVISOR = Decimal('173')        # monthly gross / 173 = hourly rate
DAILY_DIVISOR = Decimal('26')          # monthly gross / 26 = daily rate
OVERTIME_PREMIUM = Decimal('0.25')
HOLIDAY_WORK_PREMIUM = Decimal('0.50')
SICK_FULL_PAY_DAYS = 3                 # per episode, paid at 100 %
SICK_REDUCTION = Decimal('0.25')       # from day 4: paid at 75 %
LEAVE_DAYS_PER_YEAR = Decimal('26')
TFR_DIVISOR = Decimal('13.5')
INPS_EMPLOYEE_RATE = Decimal('0.0919')
IRPEF_FLAT_RATE = Decimal('0.23')      # simplified: flat, no brackets, no deductions
ACCRUAL_MIN_DAYS = 15                  # a month counts for 13th and leave if employed >= 15 days

# Italian national holidays in H1 2026 (Easter Sunday is always a Sunday and gets no extra pay)
PUBLIC_HOLIDAYS = ['2026-01-01', '2026-01-06', '2026-04-06', '2026-04-25', '2026-05-01', '2026-06-02']

LINE_DESCRIPTIONS = {
    'BASE': 'Retribuzione base',
    'STR': 'Straordinario +25%',
    'FEST': 'Festività in giorno di riposo',
    'FESTLAV': 'Lavoro festivo +50%',
    'MAL': 'Riduzione malattia (dal 4° giorno)',
    'RAT13': 'Rateo tredicesima',
    'FERIE': 'Ferie non godute',
    'TFR': 'Trattamento di fine rapporto',
}
UNTAXED_LINES = {'TFR'}  # TFR has separate taxation in Italy: out of scope, paid gross


def _cents(x):
    return Decimal(x).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _d(x):
    return Decimal(str(x))


def hourly_rate(monthly_gross):
    return _d(monthly_gross) / HOURLY_DIVISOR


def daily_rate(monthly_gross):
    return _d(monthly_gross) / DAILY_DIVISOR


def base_pay(monthly_gross, days, days_in_month):
    return _cents(_d(monthly_gross) * days / days_in_month)


def overtime_pay(monthly_gross, hours):
    return _cents(_d(hours) * hourly_rate(monthly_gross) * (1 + OVERTIME_PREMIUM))


def holiday_work_pay(monthly_gross, hours):
    return _cents(_d(hours) * hourly_rate(monthly_gross) * (1 + HOLIDAY_WORK_PREMIUM))


def sick_adjustment(monthly_gross, episode_days):
    reduced_days = sum(max(0, d - SICK_FULL_PAY_DAYS) for d in episode_days)
    return -_cents(reduced_days * daily_rate(monthly_gross) * SICK_REDUCTION)


def _month_bounds(month):
    y, m = map(int, month.split('-'))
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def _employment_window(employee, month):
    first, last = _month_bounds(month)
    start = max(first, date.fromisoformat(employee['hire_date']))
    end = min(last, date.fromisoformat(employee['termination_date'])) if employee['termination_date'] else last
    return start, end


def days_employed(employee, month):
    start, end = _employment_window(employee, month)
    return max(0, (end - start).days + 1)


def rest_day_holidays(month, start, end):
    """Public holidays on a Saturday or Sunday between start and end (inclusive)."""
    return [h for h in PUBLIC_HOLIDAYS
            if h.startswith(month) and start <= h <= end and date.fromisoformat(h).weekday() >= 5]


def totals(lines):
    gross = sum((_d(l['amount']) for l in lines if l['code'] not in UNTAXED_LINES), Decimal('0'))
    tfr = sum((_d(l['amount']) for l in lines if l['code'] in UNTAXED_LINES), Decimal('0'))
    inps = _cents(gross * INPS_EMPLOYEE_RATE)
    irpef = _cents((gross - inps) * IRPEF_FLAT_RATE)
    net = gross - inps - irpef + tfr
    return {k: float(_cents(v)) for k, v in
            (('gross', gross), ('inps_employee', inps), ('irpef', irpef), ('tfr', tfr), ('net_pay', net))}


def _line(code, amount, quantity=None, unit=None, rate=None):
    return {'code': code, 'description': LINE_DESCRIPTIONS[code], 'quantity': quantity, 'unit': unit,
            'rate': float(_cents(rate)) if rate is not None else None, 'amount': float(amount)}


def compute_payslip(employee, attendance_ytd):
    """Expected payslip for the last month in attendance_ytd (rows for the same employee, sorted by month)."""
    row = attendance_ytd[-1]
    month = row['month']
    gross = _d(employee['contract']['monthly_gross'])
    first, last = _month_bounds(month)
    days = days_employed(employee, month)
    lines = [_line('BASE', base_pay(gross, days, (last - first).days + 1), days, 'days')]

    if row['overtime_hours']:
        lines.append(_line('STR', overtime_pay(gross, row['overtime_hours']), row['overtime_hours'], 'hours',
                           hourly_rate(gross) * (1 + OVERTIME_PREMIUM)))
    start, end = _employment_window(employee, month)
    rest_days = rest_day_holidays(month, start.isoformat(), end.isoformat())
    if rest_days:
        lines.append(_line('FEST', _cents(len(rest_days) * daily_rate(gross)), len(rest_days), 'days', daily_rate(gross)))
    holiday_hours = sum(_d(h['hours']) for h in row['holiday_work'])
    if holiday_hours:
        lines.append(_line('FESTLAV', holiday_work_pay(gross, holiday_hours), float(holiday_hours), 'hours',
                           hourly_rate(gross) * (1 + HOLIDAY_WORK_PREMIUM)))
    sick = sick_adjustment(gross, [e['days'] for e in row['sick_episodes']])
    if sick:
        reduced = sum(max(0, e['days'] - SICK_FULL_PAY_DAYS) for e in row['sick_episodes'])
        lines.append(_line('MAL', sick, reduced, 'days', -daily_rate(gross) * SICK_REDUCTION))

    if employee['termination_date'] and employee['termination_date'].startswith(month):
        lines += _termination_lines(employee, attendance_ytd, gross)

    return {'lines': lines, 'totals': totals(lines)}


def _termination_lines(employee, attendance_ytd, gross):
    accrued_months = sum(1 for r in attendance_ytd if days_employed(employee, r['month']) >= ACCRUAL_MIN_DAYS)
    leave_taken = sum(_d(r['leave_days_taken']) for r in attendance_ytd)
    leave_balance = (_d(employee['opening_balances']['leave_days'])
                     + LEAVE_DAYS_PER_YEAR / 12 * accrued_months - leave_taken)
    base_ytd = Decimal('0')
    for r in attendance_ytd:
        first, last = _month_bounds(r['month'])
        base_ytd += base_pay(gross, days_employed(employee, r['month']), (last - first).days + 1)
    tfr = _cents(_d(employee['opening_balances']['tfr_fund']) + base_ytd / TFR_DIVISOR)
    lines = [_line('RAT13', _cents(gross * accrued_months / 12), accrued_months, 'months', gross / 12)]
    if leave_balance > 0:
        lines.append(_line('FERIE', _cents(leave_balance * daily_rate(gross)),
                           float(leave_balance.quantize(Decimal('0.01'))), 'days', daily_rate(gross)))
    lines.append(_line('TFR', tfr))
    return lines
