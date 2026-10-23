"""Message framing between the parent and the enclave: 8-byte big-endian length, then UTF-8 JSON.

Works on any stream socket (AF_VSOCK in production, socketpair in tests).
"""
import json
import struct

MAX_BYTES = 64 * 1024 * 1024  # refuse anything larger: protects the enclave's memory


def send_msg(sock, obj):
    data = json.dumps(obj).encode()
    sock.sendall(struct.pack('>Q', len(data)) + data)


def _recv_exact(sock, n):
    chunks, remaining = [], n
    while remaining:
        chunk = sock.recv(min(remaining, 1 << 20))
        if not chunk:
            raise ConnectionError('connection closed in the middle of a message')
        chunks.append(chunk)
        remaining -= len(chunk)
    return b''.join(chunks)


def recv_msg(sock):
    (size,) = struct.unpack('>Q', _recv_exact(sock, 8))
    if size > MAX_BYTES:
        raise ValueError(f'message of {size} bytes is above the {MAX_BYTES}-byte limit')
    return json.loads(_recv_exact(sock, size))
