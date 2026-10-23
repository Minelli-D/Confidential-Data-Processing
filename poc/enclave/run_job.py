"""Parent side of a run (spec, section 5, steps 1-4 and 8-9). Started by run_job.sh on the EC2 instance.

The parent is an untrusted courier: it downloads the envelope, passes it with the role's temporary
credentials to the enclave over vsock, and uploads the report the enclave sends back.
"""
import argparse
import datetime
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'payslip'))
import envelope as ev  # noqa: E402
from vsock_proto import recv_msg, send_msg  # noqa: E402

IMDS = 'http://169.254.169.254/latest'
ENCLAVE_PORT = 5000
ENVELOPE_KEY = 'input/payslips-2026-H1.envelope.json'


def imds_http(method, url, headers):
    req = urllib.request.Request(url, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=3) as resp:
        return resp.read().decode()


def imds_credentials(http=imds_http):
    """IMDSv2: a session token first, then the instance role's temporary credentials."""
    token = http('PUT', f'{IMDS}/api/token', {'X-aws-ec2-metadata-token-ttl-seconds': '900'})
    auth = {'X-aws-ec2-metadata-token': token}
    role = http('GET', f'{IMDS}/meta-data/iam/security-credentials/', auth).strip().splitlines()[0]
    creds = json.loads(http('GET', f'{IMDS}/meta-data/iam/security-credentials/{role}', auth))
    return {'access_key_id': creds['AccessKeyId'], 'secret_access_key': creds['SecretAccessKey'],
            'session_token': creds['Token']}


def enclave_cid(run=subprocess.run):
    out = run(['nitro-cli', 'describe-enclaves'], capture_output=True, text=True, check=True).stdout
    enclaves = json.loads(out)
    if not enclaves:
        raise RuntimeError('no enclave is running: start it with nitro-cli run-enclave')
    return enclaves[0]['EnclaveCID']


def call_enclave(cid, port, request, wait_seconds=60):
    """Connect over vsock (retrying while the enclave boots), send the request, wait for the reply."""
    deadline = time.time() + wait_seconds
    while True:
        sock = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
        try:
            sock.connect((cid, port))
            break
        except OSError:
            sock.close()
            if time.time() > deadline:
                raise
            time.sleep(2)
    with sock:
        send_msg(sock, request)
        return recv_msg(sock)


def aws_cli(args):
    return subprocess.run(['aws', *args], check=True, capture_output=True, text=True).stdout


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


def run(bucket, region, out_dir, aws=aws_cli, http=imds_http, cid=enclave_cid, call=call_enclave, now=utcnow):
    os.makedirs(out_dir, exist_ok=True)
    local = os.path.join(out_dir, os.path.basename(ENVELOPE_KEY))
    aws(['s3', 'cp', f's3://{bucket}/{ENVELOPE_KEY}', local, '--region', region])
    with open(local) as f:
        envelope = json.load(f)
    ev.validate_envelope(envelope)  # never hand the enclave anything that is not an envelope

    request = {'credentials': imds_credentials(http=http), 'region': region, 'envelope': envelope}
    response = call(cid(), ENCLAVE_PORT, request)
    status = response.get('status', {})
    print('status:', json.dumps(status))
    if not status.get('ok'):
        return 2

    report = response['report']
    if hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest() != status.get('report_sha256'):
        print('refused: the report does not match the hash in the status line')
        return 3
    name = f"report-{envelope['aad']}-{now():%Y%m%dT%H%M%SZ}.json"
    path = os.path.join(out_dir, name)
    with open(path, 'w') as f:
        json.dump(report, f, indent=2)
    aws(['s3', 'cp', path, f's3://{bucket}/reports/{name}', '--region', region])
    print(f'report uploaded to s3://{bucket}/reports/{name}')
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--bucket', required=True)
    ap.add_argument('--region', default='eu-north-1')
    ap.add_argument('--out-dir', default='/opt/poc/reports')
    a = ap.parse_args()
    sys.exit(run(a.bucket, a.region, a.out_dir))


if __name__ == '__main__':
    main()
