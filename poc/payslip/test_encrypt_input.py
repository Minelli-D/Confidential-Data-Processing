"""Tests for encrypt_input.py (step 2a-2f), with a fake AWS CLI: no AWS account involved."""
import base64
import json
import os
import tempfile
import unittest

import encrypt_input as ei
import envelope as ev

KEY_ARN = 'arn:aws:kms:eu-north-1:123456789012:key/test'


class FakeAws:
    """Stands in for the AWS CLI: records every call, answers generate-data-key like KMS does."""

    def __init__(self):
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        if args[:2] == ['kms', 'generate-data-key']:
            return json.dumps({'KeyId': KEY_ARN, 'Plaintext': base64.b64encode(bytes(32)).decode(),
                               'CiphertextBlob': base64.b64encode(b'edk').decode()})
        return ''


class EncryptInput(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, 'payslips-2026-H1.json')
        self.write_dataset({'dataset': {'id': 'payslip-reconciliation-2026-H1', 'synthetic': True},
                            'employees': [{'first_name': 'Anna', 'last_name': 'Fabbri'}]})

    def write_dataset(self, obj):
        with open(self.src, 'w') as f:
            json.dump(obj, f)

    def run_it(self, aws, **kw):
        args = dict(bucket='poc-bucket', key='alias/confidential-poc', region='eu-north-1', out_dir=self.tmp, aws=aws)
        args.update(kw)
        return ei.run(self.src, **args)

    def test_uploads_only_the_envelope_to_input(self):
        aws = FakeAws()
        result = self.run_it(aws)
        upload = aws.calls[-1]
        self.assertEqual(upload[:4], ['s3', 'cp', result['envelope_path'],
                                      's3://poc-bucket/input/payslips-2026-H1.envelope.json'])
        self.assertEqual(result['s3_uri'], 's3://poc-bucket/input/payslips-2026-H1.envelope.json')

    def test_envelope_is_valid_and_bound_to_the_dataset_id(self):
        result = self.run_it(FakeAws())
        with open(result['envelope_path']) as f:
            env = json.load(f)
        ev.validate_envelope(env)
        self.assertEqual((env['aad'], env['kms_key_id']), ('payslip-reconciliation-2026-H1', KEY_ARN))

    def test_encrypted_data_key_is_kept_for_the_negative_test(self):
        result = self.run_it(FakeAws())
        with open(result['datakey_path'], 'rb') as f:
            self.assertEqual(f.read(), b'edk')

    def test_kms_call_asks_for_an_aes_256_key_without_encryption_context(self):
        aws = FakeAws()
        self.run_it(aws)
        gen = aws.calls[0]
        self.assertEqual(gen[:2], ['kms', 'generate-data-key'])
        self.assertIn('alias/confidential-poc', gen)
        self.assertIn('AES_256', gen)
        self.assertNotIn('--encryption-context', gen)  # kmstool in the enclave cannot pass one

    def test_plaintext_is_never_written_to_the_output_folder(self):
        self.run_it(FakeAws())
        for name in os.listdir(self.tmp):
            if name.endswith(('.envelope.json', '.datakey.bin')):
                with open(os.path.join(self.tmp, name), 'rb') as f:
                    self.assertNotIn(b'Anna', f.read())

    def test_no_upload_mode_does_not_call_s3(self):
        aws = FakeAws()
        self.run_it(aws, bucket=None, upload=False)
        self.assertFalse(any(c[:2] == ['s3', 'cp'] for c in aws.calls))

    def test_refuses_a_dataset_that_is_not_marked_synthetic(self):
        self.write_dataset({'dataset': {'id': 'real-payroll', 'synthetic': False}})
        aws = FakeAws()
        with self.assertRaises(ValueError):
            self.run_it(aws)
        self.assertEqual(aws.calls, [])  # refused before asking KMS for anything


if __name__ == '__main__':
    unittest.main()
