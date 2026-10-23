"""Mode A reconciliation: recompute every issued payslip and report line-level differences.

This is the logic that will run inside the enclave. Locally:
    python3 reconcile.py ../../data/payslips-2026-H1.json [--answer-key ../../data/answer-key-2026-H1.json]
"""
import argparse
import json
from collections import defaultdict
from decimal import Decimal

import payroll_rules as pr


def _amounts(lines):
    return {l['code']: Decimal(str(l['amount'])) for l in lines}


def reconcile(dataset):
    if dataset['dataset']['rules_version'] != pr.RULES_VERSION:
        raise ValueError(f"dataset expects rules {dataset['dataset']['rules_version']}, "
                         f"this build implements {pr.RULES_VERSION}")
    employees = {e['employee_id']: e for e in dataset['employees']}
    attendance = defaultdict(list)
    for row in sorted(dataset['attendance'], key=lambda r: r['month']):
        attendance[row['employee_id']].append(row)

    findings, net_difference, with_differences = [], Decimal('0'), 0
    for p in dataset['payslips']:
        ytd = [r for r in attendance[p['employee_id']] if r['month'] <= p['month']]
        expected = pr.compute_payslip(employees[p['employee_id']], ytd)
        exp, iss = _amounts(expected['lines']), _amounts(p['lines'])
        diffs = [(code, exp.get(code, Decimal('0')), iss.get(code, Decimal('0')))
                 for code in sorted(exp.keys() | iss.keys()) if exp.get(code) != iss.get(code)]
        for code, e, i in diffs:
            findings.append({'payslip_id': p['payslip_id'], 'employee_id': p['employee_id'], 'month': p['month'],
                             'line': code, 'description': pr.LINE_DESCRIPTIONS.get(code, code),
                             'expected': float(e), 'issued': float(i), 'difference': float(i - e)})
        if diffs:
            with_differences += 1
            net_difference += Decimal(str(p['totals']['net_pay'])) - Decimal(str(expected['totals']['net_pay']))

    return {'rules_version': pr.RULES_VERSION,
            'summary': {'payslips_checked': len(dataset['payslips']),
                        'payslips_with_differences': with_differences,
                        'net_difference': float(net_difference)},
            'findings': findings}


def score(findings, answer_key):
    """Compare findings with the answer key on (payslip_id, line)."""
    key = lambda x: (x['payslip_id'], x['line'])
    found, planted = {key(f) for f in findings}, {key(a) for a in answer_key}
    pick = lambda items, keys: [{'payslip_id': i['payslip_id'], 'line': i['line']} for i in items if key(i) in keys]
    return {'matched': len(found & planted),
            'missed': pick(answer_key, planted - found),
            'unexpected': pick(findings, found - planted)}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('dataset')
    ap.add_argument('--answer-key')
    ap.add_argument('--out', help='write the full report as JSON')
    args = ap.parse_args()
    report = reconcile(json.load(open(args.dataset)))
    s = report['summary']
    print(f"rules {report['rules_version']}: {s['payslips_checked']} payslips checked, "
          f"{s['payslips_with_differences']} with differences, net impact {s['net_difference']:+.2f} EUR")
    if args.answer_key:
        sc = score(report['findings'], json.load(open(args.answer_key))['planted_errors'])
        report['score'] = sc
        print(f"answer key: {sc['matched']} matched, {len(sc['missed'])} missed, {len(sc['unexpected'])} unexpected")
    if args.out:
        json.dump(report, open(args.out, 'w'), indent=2, ensure_ascii=False)


if __name__ == '__main__':
    main()
