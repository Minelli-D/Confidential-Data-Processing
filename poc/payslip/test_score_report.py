"""Tests for score_report.py: the report downloaded from S3 vs the answer key (test A)."""
import json
import os
import tempfile
import unittest

import generate_dataset as gd
import reconcile as rc
import score_report as sr

DATASET, ANSWER_KEY = gd.generate(seed=gd.DEFAULT_SEED)
REPORT = rc.reconcile(DATASET)


class ScoreReport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.key_path = self.write('answer-key.json', ANSWER_KEY)

    def write(self, name, obj):
        path = os.path.join(self.tmp, name)
        with open(path, 'w') as f:
            json.dump(obj, f)
        return path

    def test_a_perfect_report_scores_29_0_0_and_exits_0(self):
        report_path = self.write('report.json', REPORT)
        result = sr.score_files(report_path, self.key_path)
        self.assertEqual((result['matched'], len(result['missed']), len(result['unexpected'])), (29, 0, 0))
        self.assertEqual(sr.main([report_path, '--answer-key', self.key_path]), 0)

    def test_a_missed_error_exits_1(self):
        partial = dict(REPORT, findings=REPORT['findings'][1:])
        report_path = self.write('report.json', partial)
        self.assertEqual(len(sr.score_files(report_path, self.key_path)['missed']), 1)
        self.assertEqual(sr.main([report_path, '--answer-key', self.key_path]), 1)


if __name__ == '__main__':
    unittest.main()
