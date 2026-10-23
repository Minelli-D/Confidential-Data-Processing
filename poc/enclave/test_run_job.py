"""Tests for the parent-side job runner, with fake IMDS, fake AWS CLI and a fake enclave."""
import datetime
import hashlib
import json
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'payslip'))
import envelope as ev  # noqa: E402
import run_job as rj  # noqa: E402

ENVELOPE = ev.seal(b'{"dataset": {}}', aad='payslip-reconciliation-2026-H1', data_key=bytearray(32),
                   encrypted_data_key=b'edk', kms_key_id='arn:aws:kms:eu-north-1:123456789012:key/test')
REPORT = {'rules_version': 'it-simplified-0.1', 'summary': {'payslips_checked': 580}, 'findings': []}
REPORT_SHA = hashlib.sha256(json.dumps(REPORT, sort_keys=True).encode()).hexdigest()
NOW = datetime.datetime(2026, 10, 2, 9, 30, 0, tzinfo=datetime.timezone.utc)


class FakeHttp:
    def __init__(self):
        self.calls = []

    def __call__(self, method, url, headers):
        self.calls.append((method, url, headers))
        if url.endswith('/api/token'):
            return 'TOKEN'
        if url.endswith('/security-credentials/'):
            return 'confidential-poc-instance\n'
        return json.dumps({'AccessKeyId': 'AKIA1', 'SecretAccessKey': 'S1', 'Token': 'T1'})


class FakeAws:
    def __init__(self, envelope=ENVELOPE):
        self.calls, self.envelope = [], envelope

    def __call__(self, args):
        self.calls.append(args)
        if args[:2] == ['s3', 'cp'] and args[2].startswith('s3://'):
            with open(args[3], 'w') as f:
                json.dump(self.envelope, f)
        return ''

    def uploads(self):
        return [c for c in self.calls if c[:2] == ['s3', 'cp'] and c[3].startswith('s3://')]


class Imds(unittest.TestCase):
    def test_credentials_come_from_imdsv2_with_a_token(self):
        http = FakeHttp()
        creds = rj.imds_credentials(http=http)
        self.assertEqual(creds, {'access_key_id': 'AKIA1', 'secret_access_key': 'S1', 'session_token': 'T1'})
        method, url, headers = http.calls[0]
        self.assertEqual((method, url.endswith('/api/token')), ('PUT', True))
        self.assertIn('X-aws-ec2-metadata-token-ttl-seconds', headers)
        for method, url, headers in http.calls[1:]:
            self.assertEqual(headers.get('X-aws-ec2-metadata-token'), 'TOKEN')


class EnclaveCid(unittest.TestCase):
    def run_with(self, stdout):
        return lambda cmd, **kw: types.SimpleNamespace(returncode=0, stdout=stdout, stderr='')

    def test_cid_of_the_running_enclave(self):
        self.assertEqual(rj.enclave_cid(run=self.run_with('[{"EnclaveCID": 16, "State": "RUNNING"}]')), 16)

    def test_no_enclave_is_an_error(self):
        with self.assertRaises(RuntimeError):
            rj.enclave_cid(run=self.run_with('[]'))


class Run(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp()
        self.sent = []

    def enclave_replying(self, response):
        def call(cid, port, request):
            self.sent.append((cid, port, request))
            return response
        return call

    def run_job(self, aws, response):
        return rj.run('poc-bucket', 'eu-north-1', self.out, aws=aws, http=FakeHttp(), cid=lambda: 16,
                      call=self.enclave_replying(response), now=lambda: NOW)

    def test_success_stores_the_report_and_uploads_it_to_reports(self):
        aws = FakeAws()
        code = self.run_job(aws, {'status': {'ok': True, 'report_sha256': REPORT_SHA}, 'report': REPORT})
        self.assertEqual(code, 0)
        name = 'report-payslip-reconciliation-2026-H1-20261002T093000Z.json'
        with open(os.path.join(self.out, name)) as f:
            self.assertEqual(json.load(f), REPORT)
        self.assertEqual(aws.uploads()[0][2:4], [os.path.join(self.out, name), f's3://poc-bucket/reports/{name}'])

    def test_the_enclave_receives_envelope_credentials_and_region(self):
        self.run_job(FakeAws(), {'status': {'ok': True, 'report_sha256': REPORT_SHA}, 'report': REPORT})
        cid, port, request = self.sent[0]
        self.assertEqual((cid, port), (16, 5000))
        self.assertEqual(request['envelope'], ENVELOPE)
        self.assertEqual(request['region'], 'eu-north-1')
        self.assertEqual(request['credentials']['session_token'], 'T1')

    def test_enclave_error_uploads_nothing(self):
        aws = FakeAws()
        code = self.run_job(aws, {'status': {'ok': False, 'error': 'KmsError', 'message': 'AccessDenied'}})
        self.assertEqual(code, 2)
        self.assertEqual(aws.uploads(), [])

    def test_report_that_does_not_match_its_hash_is_not_uploaded(self):
        aws = FakeAws()
        code = self.run_job(aws, {'status': {'ok': True, 'report_sha256': '0' * 64}, 'report': REPORT})
        self.assertEqual(code, 3)
        self.assertEqual(aws.uploads(), [])

    def test_a_downloaded_file_that_is_not_an_envelope_never_reaches_the_enclave(self):
        aws = FakeAws(envelope={'dataset': {}, 'employees': []})
        with self.assertRaises(ValueError):
            self.run_job(aws, {'status': {'ok': True}})
        self.assertEqual(self.sent, [])


if __name__ == '__main__':
    unittest.main()
