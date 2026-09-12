"""Focused egress policy/tunnel checks with no internet requests."""
import ipaddress
import socket
import threading
import unittest
from unittest.mock import Mock, patch

import egress


def endpoint(address):
    version = ipaddress.ip_address(address).version
    family = socket.AF_INET if version == 4 else socket.AF_INET6
    sockaddr = (address, 443) if version == 4 else (address, 443, 0, 0)
    return family, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', sockaddr


class EgressPolicyTests(unittest.TestCase):
    def test_only_exact_reviewed_hosts_on_443(self):
        for host in egress.ALLOWED_HOSTS:
            with self.subTest(host=host):
                self.assertEqual(egress.validate_authority(f'{host}:443'), (host, 443))
        self.assertEqual(egress.validate_authority('API.OPENAI.COM:443'), ('api.openai.com', 443))
        rejected = ('api.openai.com.evil.test:443', 'api.openai.com.:443',
                    'api.openai.com@127.0.0.1:443', '127.0.0.1:443', '[::1]:443',
                    '8.8.8.8:443', 'localhost:443', 'api.openai.com:80',
                    'api.openai.com:0443', 'api.openai.com:+443',
                    'api.openai.com:443/path', 'api.openai.com')
        for authority in rejected:
            with self.subTest(authority=authority), self.assertRaises(egress.PolicyError):
                egress.validate_authority(authority)

    def test_non_connect_methods_and_invalid_requests_are_rejected(self):
        for method in ('GET', 'POST', 'OPTIONS', 'connect'):
            with self.subTest(method=method), self.assertRaises(egress.RequestError) as caught:
                egress.parse_request(f'{method} api.openai.com:443 HTTP/1.1'.encode())
            self.assertEqual(caught.exception.status, 405)
        for request in (b'CONNECT api.openai.com:443',
                        b'CONNECT api.openai.com:443 HTTP/2',
                        b'CONNECT api.openai.com:443 HTTP/1.1\r\n malformed: value',
                        b'CONNECT api.openai.com:443 HTTP/1.1\r\nmalformed',
                        b'CONNECT api.openai.com:443 HTTP/1.1\r\nX: \xff'):
            with self.subTest(request=request), self.assertRaises(egress.RequestError):
                egress.parse_request(request)

    def test_private_local_special_and_reserved_addresses_are_rejected(self):
        rejected = ('0.0.0.0', '127.0.0.1', '10.1.2.3', '172.16.0.1',
                    '192.168.1.1', '169.254.169.254', '100.64.0.1',
                    '192.0.2.1', '224.0.0.1', '240.0.0.1', '255.255.255.255',
                    '::', '::1', 'fe80::1', 'fc00::1', 'ff02::1', '2001:db8::1',
                    '::ffff:127.0.0.1', '::ffff:10.0.0.1', '64:ff9b::a00:1')
        for address in rejected:
            with self.subTest(address=address):
                self.assertFalse(egress.public_address(address))
                with patch.object(egress.socket, 'getaddrinfo', return_value=[endpoint(address)]):
                    with self.assertRaises(egress.PolicyError):
                        egress.resolve_target('api.openai.com', 443)

    def test_public_ipv4_and_ipv6_are_accepted(self):
        results = [endpoint('8.8.8.8'), endpoint('2606:4700:4700::1111')]
        with patch.object(egress.socket, 'getaddrinfo', return_value=results):
            addresses = egress.resolve_target('api.openai.com', 443)
        self.assertEqual([item[3] for item in addresses], [item[4] for item in results])

    def test_mixed_dns_answers_fail_before_any_connection(self):
        results = [endpoint('8.8.8.8'), endpoint('127.0.0.1')]
        with patch.object(egress.socket, 'getaddrinfo', return_value=results), \
                patch.object(egress.socket, 'socket') as socket_factory:
            with self.assertRaises(egress.PolicyError):
                egress.connect_target('api.openai.com', 443)
            socket_factory.assert_not_called()

    def test_connection_uses_validated_sockaddr_without_second_dns_lookup(self):
        resolved = endpoint('8.8.8.8')
        connection = Mock()
        with patch.object(egress.socket, 'getaddrinfo', return_value=[resolved]) as resolver, \
                patch.object(egress.socket, 'socket', return_value=connection):
            self.assertIs(egress.connect_target('api.openai.com', 443), connection)
        resolver.assert_called_once_with('api.openai.com', 443, type=socket.SOCK_STREAM,
                                         proto=socket.IPPROTO_TCP)
        connection.connect.assert_called_once_with(('8.8.8.8', 443))

    def test_request_reader_preserves_immediate_tunnel_bytes(self):
        client, proxy = socket.socketpair()
        self.addCleanup(client.close)
        self.addCleanup(proxy.close)
        client.sendall(b'CONNECT api.openai.com:443 HTTP/1.1\r\nHost: api.openai.com:443\r\n\r\n\x16\x03\x01')
        headers, initial = egress.read_request(proxy)
        self.assertEqual(egress.parse_request(headers), ('api.openai.com', 443))
        self.assertEqual(initial, b'\x16\x03\x01')

    def test_tunnel_moves_bytes_both_ways_and_preserves_half_close(self):
        client, left = socket.socketpair()
        right, upstream = socket.socketpair()
        for connection in (client, left, right, upstream):
            self.addCleanup(connection.close)
            connection.settimeout(2)
        errors = []

        def forward():
            try:
                with left, right:
                    egress.tunnel(left, right, b'initial')
            except Exception as error:
                errors.append(error)

        worker = threading.Thread(target=forward, daemon=True)
        worker.start()
        self.assertEqual(upstream.recv(7), b'initial')
        client.sendall(b'client bytes')
        self.assertEqual(upstream.recv(12), b'client bytes')
        upstream.sendall(b'server bytes')
        self.assertEqual(client.recv(12), b'server bytes')
        client.shutdown(socket.SHUT_WR)
        self.assertEqual(upstream.recv(1), b'')
        upstream.sendall(b'after half close')
        self.assertEqual(client.recv(16), b'after half close')
        upstream.shutdown(socket.SHUT_WR)
        self.assertEqual(client.recv(1), b'')
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
