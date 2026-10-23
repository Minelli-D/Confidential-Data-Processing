"""Tests for the parent <-> enclave message framing (8-byte length + JSON)."""
import socket
import struct
import threading
import unittest

import vsock_proto as vp


class Framing(unittest.TestCase):
    def setUp(self):
        self.a, self.b = socket.socketpair()

    def tearDown(self):
        self.a.close()
        self.b.close()

    def test_round_trip(self):
        vp.send_msg(self.a, {'hello': 'enclave', 'n': 1})
        self.assertEqual(vp.recv_msg(self.b), {'hello': 'enclave', 'n': 1})

    def test_large_message_arrives_whole(self):
        big = {'blob': 'x' * 2_000_000}
        sender = threading.Thread(target=vp.send_msg, args=(self.a, big))
        sender.start()
        self.assertEqual(vp.recv_msg(self.b), big)
        sender.join()

    def test_declared_size_above_the_limit_is_refused(self):
        self.a.sendall(struct.pack('>Q', vp.MAX_BYTES + 1))
        with self.assertRaises(ValueError):
            vp.recv_msg(self.b)

    def test_connection_closed_mid_message_is_an_error(self):
        self.a.sendall(struct.pack('>Q', 100) + b'{"partial"')
        self.a.close()
        with self.assertRaises(ConnectionError):
            vp.recv_msg(self.b)


if __name__ == '__main__':
    unittest.main()
