"""Tests for the enclave application, with a local test key instead of KMS (the free local dry run)."""
import base64
import hashlib
import json
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'payslip'))
import envelope as ev  # noqa: E402
import generate_dataset as gd  # noqa: E402
import reconcile as rc  # noqa: E402
import enclave_app as app  # noqa: E402

KEY = bytes(range(32))
EDK = b'encrypted-data-key'
CREDS = {'access_key_id': 'AKIAEXAMPLE', 'secret_access_key': 'SECRET-EXAMPLE', 'session_token': 'TOKEN-EXAMPLE'}
DATASET, ANSWER_KEY = gd.generate(seed=gd.DEFAULT_SEED)


def request_for(dataset=DATASET):
    raw = json.dumps(dataset).encode()
    env = ev.seal(raw, aad=dataset['dataset']['id'], data_key=bytearray(KEY), encrypted_data_key=EDK,
                  kms_key_id='arn:aws:kms:eu-north-1:123456789012:key/test')
    return {'credentials': CREDS, 'region': 'eu-north-1', 'envelope': env}


def local_kms(edk):
    if edk != EDK:
        raise app.KmsError('AccessDeniedException')
    return bytearray(KEY)


class LocalDryRun(unittest.TestCase):
    def test_enclave_logic_finds_exactly_the_planted_errors(self):
        resp = app.handle(request_for(), decrypt=local_kms)
        self.assertTrue(resp['status']['ok'])
        self.assertEqual(resp['status']['payslips_checked'], 580)
        s = rc.score(resp['report']['findings'], ANSWER_KEY['planted_errors'])
        self.assertEqual((s['matched'], s['missed'], s['unexpected']), (29, [], []))

    def test_status_carries_the_hash_of_the_report(self):
        resp = app.handle(request_for(), decrypt=local_kms)
        body = json.dumps(resp['report'], sort_keys=True).encode()
        self.assertEqual(resp['status']['report_sha256'], hashlib.sha256(body).hexdigest())

    def test_status_line_has_no_personal_data(self):
        status = json.dumps(app.handle(request_for(), decrypt=local_kms)['status'])
        self.assertNotIn(DATASET['employees'][0]['last_name'], status)
        self.assertNotIn('PS-2026', status)
        self.assertNotIn('E0', status)


class Refusals(unittest.TestCase):
    def assert_refused(self, resp, error):
        self.assertFalse(resp['status']['ok'])
        self.assertEqual(resp['status']['error'], error)
        self.assertNotIn('report', resp)

    def test_tampered_envelope_is_refused(self):
        req = request_for()
        raw = bytearray(base64.b64decode(req['envelope']['ciphertext']))
        raw[10] ^= 1
        req['envelope']['ciphertext'] = base64.b64encode(bytes(raw)).decode()
        self.assert_refused(app.handle(req, decrypt=local_kms), 'InvalidTag')

    def test_kms_refusal_is_reported(self):
        def deny(edk):
            raise app.KmsError('AccessDeniedException: not authorized to perform kms:Decrypt')
        resp = app.handle(request_for(), decrypt=deny)
        self.assert_refused(resp, 'KmsError')
        self.assertIn('AccessDenied', resp['status']['message'])

    def test_input_that_is_not_an_envelope_is_refused(self):
        req = request_for()
        req['envelope'] = DATASET
        self.assert_refused(app.handle(req, decrypt=local_kms), 'ValueError')

    def test_dataset_for_other_rules_is_refused(self):
        other = json.loads(json.dumps(DATASET))
        other['dataset']['rules_version'] = 'it-simplified-9.9'
        self.assert_refused(app.handle(request_for(other), decrypt=local_kms), 'ValueError')

    def test_credentials_never_appear_in_an_error(self):
        def leaky(edk):
            raise app.KmsError(f"failed with key {CREDS['secret_access_key']} and {CREDS['session_token']}")
        message = app.handle(request_for(), decrypt=leaky)['status']['message']
        self.assertNotIn(CREDS['secret_access_key'], message)
        self.assertNotIn(CREDS['session_token'], message)


class Kmstool(unittest.TestCase):
    def fake_run(self, returncode=0, stdout='', stderr=''):
        calls = []

        def run(cmd, **kw):
            calls.append(cmd)
            return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)
        return run, calls

    def test_calls_kmstool_decrypt_through_the_parent_proxy(self):
        run, calls = self.fake_run(stdout='PLAINTEXT: ' + base64.b64encode(KEY).decode() + '\n')
        key = app.kmstool_decrypt(EDK, CREDS, 'eu-north-1', run=run)
        self.assertEqual(key, bytearray(KEY))
        cmd = calls[0]
        self.assertEqual(cmd[1], 'decrypt')
        for flag, value in [('--region', 'eu-north-1'), ('--proxy-port', '8000'),
                            ('--aws-access-key-id', 'AKIAEXAMPLE'), ('--aws-secret-access-key', 'SECRET-EXAMPLE'),
                            ('--aws-session-token', 'TOKEN-EXAMPLE'),
                            ('--ciphertext', base64.b64encode(EDK).decode())]:
            self.assertEqual(cmd[cmd.index(flag) + 1], value)

    def test_a_failed_kmstool_call_raises(self):
        run, _ = self.fake_run(returncode=1, stderr='AccessDeniedException\nmore detail')
        with self.assertRaises(app.KmsError) as ctx:
            app.kmstool_decrypt(EDK, CREDS, 'eu-north-1', run=run)
        self.assertIn('AccessDenied', str(ctx.exception))

    def test_output_without_plaintext_raises(self):
        run, _ = self.fake_run(stdout='something else')
        with self.assertRaises(app.KmsError):
            app.kmstool_decrypt(EDK, CREDS, 'eu-north-1', run=run)


if __name__ == '__main__':
    unittest.main()
