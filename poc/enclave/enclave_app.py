"""The application inside the Nitro Enclave (spec, section 5). PCR0 measures this file.

Listens on vsock port 5000. For each request {credentials, region, envelope}:
  kmstool (attestation + KMS Decrypt) -> data key -> AES-GCM decrypt in memory -> Mode A -> reply.
Reply: {status, report}. The status line has no personal data; the report is in clear in the POC
(decision AWS-8). On any error, only {status} is returned, never data.
"""
import base64
import hashlib
import json
import os
import socket
import subprocess
import sys

# In the image all modules sit in /app; locally the formulas live in ../payslip
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'payslip'))
import envelope as ev  # noqa: E402
import reconcile as rc  # noqa: E402
from vsock_proto import recv_msg, send_msg  # noqa: E402

PORT = 5000
PROXY_PORT = 8000  # vsock-proxy on the parent forwards this port to KMS
KMSTOOL = os.environ.get('KMSTOOL', '/app/kmstool_enclave_cli')
SAFE_ERRORS = ('KmsError', 'InvalidTag', 'ValueError')


class KmsError(Exception):
    pass


def kmstool_decrypt(encrypted_data_key, creds, region, run=subprocess.run):
    """AWS kmstool: gets the attestation document from the Nitro hardware and calls KMS Decrypt with it.
    KMS returns the data key encrypted for this enclave only; kmstool unwraps it."""
    cmd = [KMSTOOL, 'decrypt', '--region', region, '--proxy-port', str(PROXY_PORT),
           '--aws-access-key-id', creds['access_key_id'],
           '--aws-secret-access-key', creds['secret_access_key'],
           '--aws-session-token', creds['session_token'],
           '--ciphertext', base64.b64encode(encrypted_data_key).decode()]
    result = run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        first = (result.stderr or result.stdout or 'no output').strip().splitlines()[0]
        raise KmsError(f'kmstool failed: {first}')
    for line in result.stdout.splitlines():
        if line.startswith('PLAINTEXT:'):
            return bytearray(base64.b64decode(line.split(':', 1)[1].strip()))
    raise KmsError('kmstool returned no plaintext')


def _safe_message(error, creds):
    if type(error).__name__ not in SAFE_ERRORS:
        return ''
    message = str(error)[:300]
    for secret in (creds or {}).values():
        if secret:
            message = message.replace(secret, '***')
    return message


def handle(request, decrypt=None):
    creds = request.get('credentials') if isinstance(request, dict) else None
    try:
        envelope = request['envelope']
        ev.validate_envelope(envelope)
        if decrypt is None:
            def decrypt(edk):
                return kmstool_decrypt(edk, creds, request['region'])
        dataset = json.loads(ev.open_envelope(envelope, decrypt))
        report = rc.reconcile(dataset)
        body = json.dumps(report, sort_keys=True).encode()
        status = {'ok': True, 'rules_version': report['rules_version'], **report['summary'],
                  'report_sha256': hashlib.sha256(body).hexdigest()}
        return {'status': status, 'report': report}
    except Exception as error:  # the parent only ever learns the type and a safe message
        return {'status': {'ok': False, 'error': type(error).__name__, 'message': _safe_message(error, creds)}}


def serve(port=PORT):
    server = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
    server.bind((socket.VMADDR_CID_ANY, port))
    server.listen(1)
    while True:  # runs until the parent terminates the enclave (its memory is then wiped)
        conn, _ = server.accept()
        with conn:
            send_msg(conn, handle(recv_msg(conn)))


if __name__ == '__main__':
    serve()
