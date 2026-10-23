"""poc-envelope-v1: the sealed format of the input file (spec, section 5).

The laptop seals (step 2b) and the enclave opens. The data key comes from KMS; here it is only used,
then wiped (best effort: Python can't guarantee that no copy remains in memory).
"""
import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

FORMAT = 'poc-envelope-v1'
ALGORITHM = 'AES-256-GCM'
FIELDS = ('format', 'kms_key_id', 'encrypted_data_key', 'algorithm', 'nonce', 'aad', 'ciphertext')


def _b64(raw):
    return base64.b64encode(raw).decode()


def _wipe(buf):
    if isinstance(buf, bytearray):
        for i in range(len(buf)):
            buf[i] = 0


def seal(plaintext, aad, data_key, encrypted_data_key, kms_key_id):
    """Encrypt plaintext with the plaintext data key (a bytearray, wiped afterwards)."""
    try:
        nonce = os.urandom(12)
        ciphertext = AESGCM(bytes(data_key)).encrypt(nonce, plaintext, aad.encode())
    finally:
        _wipe(data_key)
    return {'format': FORMAT, 'kms_key_id': kms_key_id, 'encrypted_data_key': _b64(encrypted_data_key),
            'algorithm': ALGORITHM, 'nonce': _b64(nonce), 'aad': aad, 'ciphertext': _b64(ciphertext)}


def validate_envelope(env):
    """Step 2f: refuse anything that is not a complete poc-envelope-v1."""
    if (not isinstance(env, dict) or any(f not in env for f in FIELDS)
            or env['format'] != FORMAT or env['algorithm'] != ALGORITHM):
        raise ValueError('not a poc-envelope-v1 envelope')


def open_envelope(env, decrypt_data_key):
    """decrypt_data_key(encrypted_data_key) -> plaintext data key. In the enclave, that is kmstool."""
    validate_envelope(env)
    data_key = decrypt_data_key(base64.b64decode(env['encrypted_data_key']))
    try:
        return AESGCM(bytes(data_key)).decrypt(base64.b64decode(env['nonce']),
                                               base64.b64decode(env['ciphertext']), env['aad'].encode())
    finally:
        _wipe(data_key)
