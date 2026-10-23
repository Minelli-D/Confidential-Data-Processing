"""Step 2 of the runbook: envelope-encrypt the payslip JSON on this laptop and upload it to S3 input/.

    python3 encrypt_input.py --bucket <bucket>                    # encrypt + upload
    python3 encrypt_input.py --no-upload                           # encrypt only

Uses the AWS CLI (your current profile / AWS_PROFILE). The plaintext JSON never leaves this laptop:
only the envelope is uploaded. The encrypted data key is also saved locally for negative test B2.
"""
import argparse
import base64
import json
import os
import subprocess

import envelope as ev

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_INPUT = os.path.join(HERE, '..', '..', 'data', 'payslips-2026-H1.json')
DEFAULT_OUT = os.path.join(HERE, '..', '..', 'data', 'encrypted')


def aws_cli(args):
    return subprocess.run(['aws', *args], check=True, capture_output=True, text=True).stdout


def run(src, bucket, key, region, out_dir, aws=aws_cli, upload=True):
    with open(src, 'rb') as f:
        raw = f.read()
    meta = json.loads(raw).get('dataset', {})
    if meta.get('synthetic') is not True:
        raise ValueError('refused: the POC accepts only datasets marked "synthetic": true (decision DATA-1)')
    if upload and not bucket:
        raise ValueError('--bucket is required to upload')

    # 2a. GenerateDataKey. No encryption context: kmstool in the enclave cannot pass one.
    resp = json.loads(aws(['kms', 'generate-data-key', '--key-id', key, '--key-spec', 'AES_256',
                           '--region', region, '--output', 'json']))
    data_key = bytearray(base64.b64decode(resp.pop('Plaintext')))
    encrypted_data_key = base64.b64decode(resp['CiphertextBlob'])

    # 2b + 2c. Encrypt locally (AES-256-GCM, bound to the dataset id), then wipe the plaintext key
    env = ev.seal(raw, aad=meta['id'], data_key=data_key, encrypted_data_key=encrypted_data_key,
                  kms_key_id=resp['KeyId'])
    ev.validate_envelope(env)  # 2f. never upload anything that is not an envelope

    name = os.path.splitext(os.path.basename(src))[0]
    os.makedirs(out_dir, exist_ok=True)
    envelope_path = os.path.join(out_dir, f'{name}.envelope.json')
    datakey_path = os.path.join(out_dir, f'{name}.datakey.bin')
    with open(envelope_path, 'w') as f:
        json.dump(env, f)
    with open(datakey_path, 'wb') as f:
        f.write(encrypted_data_key)

    # 2d. Upload over TLS; 2e. S3 adds SSE-S3 at rest (bucket default)
    s3_uri = None
    if upload:
        s3_uri = f's3://{bucket}/input/{name}.envelope.json'
        aws(['s3', 'cp', envelope_path, s3_uri, '--region', region])
    return {'envelope_path': envelope_path, 'datakey_path': datakey_path, 's3_uri': s3_uri,
            'kms_key_id': resp['KeyId'], 'aad': meta['id'], 'plaintext_bytes': len(raw)}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--input', default=DEFAULT_INPUT)
    ap.add_argument('--bucket', help='from: terraform -chdir=infra/base output -raw bucket_name')
    ap.add_argument('--key', default='alias/confidential-poc')
    ap.add_argument('--region', default='eu-north-1')
    ap.add_argument('--out-dir', default=DEFAULT_OUT)
    ap.add_argument('--no-upload', action='store_true')
    a = ap.parse_args()
    r = run(a.input, a.bucket, a.key, a.region, os.path.abspath(a.out_dir), upload=not a.no_upload)
    print(f"encrypted {r['plaintext_bytes']} bytes with a data key from {r['kms_key_id']}")
    print(f"aad (dataset id): {r['aad']}")
    print(f"envelope:           {r['envelope_path']}")
    print(f"encrypted data key: {r['datakey_path']}   (for negative test B2)")
    print(f"uploaded to:        {r['s3_uri'] or 'not uploaded (--no-upload)'}")


if __name__ == '__main__':
    main()
