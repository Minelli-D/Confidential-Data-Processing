"""Tests for the poc-envelope-v1 format (AES-256-GCM envelope), with a local test key: no KMS involved."""
import base64
import json
import unittest

from cryptography.exceptions import InvalidTag

import envelope as ev

KEY = bytes(range(32))
EDK = b'encrypted-data-key-from-kms'
ARN = 'arn:aws:kms:eu-north-1:123456789012:key/test'
AAD = 'payslip-reconciliation-2026-H1'


def sealed(plaintext=b'{"secret": 1}', aad=AAD):
    return ev.seal(plaintext, aad=aad, data_key=bytearray(KEY), encrypted_data_key=EDK, kms_key_id=ARN)


class Seal(unittest.TestCase):
    def test_envelope_has_the_documented_fields(self):
        env = sealed()
        self.assertEqual((env['format'], env['algorithm'], env['aad'], env['kms_key_id']),
                         ('poc-envelope-v1', 'AES-256-GCM', AAD, ARN))
        self.assertEqual(base64.b64decode(env['encrypted_data_key']), EDK)
        self.assertEqual(len(base64.b64decode(env['nonce'])), 12)

    def test_ciphertext_does_not_reveal_the_plaintext(self):
        env = sealed(b'Anna Fabbri 2275.65')
        self.assertNotIn(b'Anna', base64.b64decode(env['ciphertext']))
        self.assertNotIn('Anna', json.dumps(env))

    def test_plaintext_data_key_is_wiped_after_use(self):
        key = bytearray(KEY)
        ev.seal(b'x', aad=AAD, data_key=key, encrypted_data_key=EDK, kms_key_id=ARN)
        self.assertEqual(key, bytearray(32))

    def test_each_seal_uses_a_fresh_nonce(self):
        self.assertNotEqual(sealed()['nonce'], sealed()['nonce'])


class Open(unittest.TestCase):
    def test_round_trip_with_the_right_data_key(self):
        env = sealed(b'payslips')
        self.assertEqual(ev.open_envelope(env, lambda edk: bytearray(KEY) if edk == EDK else None), b'payslips')

    def test_any_change_to_the_ciphertext_is_detected(self):
        env = sealed(b'payslips')
        raw = bytearray(base64.b64decode(env['ciphertext']))
        raw[0] ^= 1
        env['ciphertext'] = base64.b64encode(bytes(raw)).decode()
        with self.assertRaises(InvalidTag):
            ev.open_envelope(env, lambda edk: bytearray(KEY))

    def test_a_different_aad_is_detected(self):
        env = sealed(b'payslips')
        env['aad'] = 'another-dataset'
        with self.assertRaises(InvalidTag):
            ev.open_envelope(env, lambda edk: bytearray(KEY))


class Validate(unittest.TestCase):
    def test_a_plain_dataset_is_not_an_envelope(self):
        with self.assertRaises(ValueError):
            ev.validate_envelope({'dataset': {}, 'employees': []})

    def test_a_sealed_envelope_is_valid(self):
        ev.validate_envelope(sealed())


if __name__ == '__main__':
    unittest.main()
