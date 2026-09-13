"""Restricted HTTPS CONNECT proxy; run alone in the egress container.

Only the reviewed endpoints below are reachable. TLS stays end to end; request
headers, tunnel contents, credentials, and errors are never logged.
"""
import ipaddress
import select
import socket
import socketserver
import threading
import time


# Add only the reviewed hostname of your own supplier deployment before running.
# Historical hackathon hosts have been retired from the default allowlist.
ALLOWED_HOSTS = frozenset({'api.openai.com', 'api.ambiguous.ai', 'app.ambiguous.ai'})
PORT = 3128
HEADER_LIMIT = 32768
HEADER_TIMEOUT = 10
CONNECT_TIMEOUT = 10
IDLE_TIMEOUT = 300
BUFFER_LIMIT = 65536
MAX_CONNECTIONS = 64


class PolicyError(ValueError):
    pass


class RequestError(ValueError):
    def __init__(self, status):
        self.status = status


def validate_authority(authority):
    """Accept only an exact reviewed DNS hostname followed by literal :443."""
    if authority.count(':') != 1:
        raise PolicyError('Invalid CONNECT authority')
    host, port = authority.split(':')
    host = host.lower()
    if host not in ALLOWED_HOSTS or port != '443':
        raise PolicyError('Destination is not allowed')
    return host, 443


def parse_request(headers):
    try:
        lines = headers.decode('ascii').split('\r\n')
    except UnicodeDecodeError:
        raise RequestError(400) from None
    parts = lines[0].split(' ')
    if len(parts) != 3 or parts[2] not in ('HTTP/1.0', 'HTTP/1.1'):
        raise RequestError(400)
    if parts[0] != 'CONNECT':
        raise RequestError(405)
    for line in lines[1:]:
        if not line:
            continue
        if ':' not in line or line[0].isspace() or '\n' in line or '\r' in line:
            raise RequestError(400)
    return validate_authority(parts[1])


def read_request(client):
    client.settimeout(HEADER_TIMEOUT)
    data = bytearray()
    while True:
        chunk = client.recv(4096)
        if not chunk:
            raise RequestError(400)
        data.extend(chunk)
        end = data.find(b'\r\n\r\n')
        if end >= 0:
            if end + 4 > HEADER_LIMIT:
                raise RequestError(431)
            return bytes(data[:end]), bytes(data[end + 4:])
        if len(data) >= HEADER_LIMIT:
            raise RequestError(431)


def public_address(value):
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    # Multicast and some reserved IPv6 ranges can report is_global=True.
    if not address.is_global or address.is_multicast or address.is_reserved:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return public_address(str(address.ipv4_mapped))
    return True


def resolve_target(host, port):
    validate_authority(f'{host}:{port}')
    results = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM,
                                 proto=socket.IPPROTO_TCP)
    if not results:
        raise OSError('No destination addresses')
    endpoints = []
    for family, kind, protocol, _, sockaddr in results:
        if (family not in (socket.AF_INET, socket.AF_INET6)
                or kind != socket.SOCK_STREAM
                or protocol not in (0, socket.IPPROTO_TCP)
                or sockaddr[1] != 443 or not public_address(sockaddr[0])):
            raise PolicyError('DNS returned a forbidden address')
        address = ipaddress.ip_address(sockaddr[0])
        if ((family == socket.AF_INET) != (address.version == 4)
                or (family == socket.AF_INET6 and sockaddr[3] != 0)):
            raise PolicyError('DNS returned an invalid address family or scope')
        endpoint = (family, kind, protocol, sockaddr)
        if endpoint not in endpoints:
            endpoints.append(endpoint)
    return endpoints


def connect_target(host, port):
    # Validate ALL results before connecting, and never resolve the name again.
    endpoints = resolve_target(host, port)
    for family, kind, protocol, sockaddr in endpoints:
        upstream = socket.socket(family, kind, protocol)
        try:
            upstream.settimeout(CONNECT_TIMEOUT)
            upstream.connect(sockaddr)
            return upstream
        except OSError:
            upstream.close()
    raise OSError('Destination connection failed')


def tunnel(client, upstream, initial=b''):
    peers = {client: upstream, upstream: client}
    pending = {client: bytearray(), upstream: bytearray(initial)}
    reading = set(peers)
    write_closed = set()
    for connection in peers:
        connection.setblocking(False)
    activity = time.monotonic()
    while reading or any(pending.values()):
        for source, destination in peers.items():
            if source not in reading and not pending[destination] and destination not in write_closed:
                destination.shutdown(socket.SHUT_WR)
                write_closed.add(destination)
        remaining = IDLE_TIMEOUT - (time.monotonic() - activity)
        if remaining <= 0:
            return
        readable, writable, _ = select.select(
            [source for source in reading if len(pending[peers[source]]) < BUFFER_LIMIT],
            [destination for destination in peers if pending[destination]], [], remaining)
        if not readable and not writable:
            return
        for source in readable:
            destination = peers[source]
            try:
                chunk = source.recv(BUFFER_LIMIT - len(pending[destination]))
            except BlockingIOError:
                continue
            if chunk:
                pending[destination].extend(chunk)
                activity = time.monotonic()
            else:
                reading.remove(source)
        for destination in writable:
            try:
                sent = destination.send(pending[destination])
            except BlockingIOError:
                continue
            if not sent:
                return
            del pending[destination][:sent]
            activity = time.monotonic()


def send_error(client, status):
    reasons = {400: 'Bad Request', 403: 'Forbidden', 405: 'Method Not Allowed',
               408: 'Request Timeout', 431: 'Request Header Fields Too Large',
               502: 'Bad Gateway', 503: 'Service Unavailable'}
    response = (f'HTTP/1.1 {status} {reasons[status]}\r\n'
                'Connection: close\r\nContent-Length: 0\r\n\r\n')
    try:
        client.settimeout(1)
        client.sendall(response.encode('ascii'))
    except OSError:
        pass


class ConnectHandler(socketserver.BaseRequestHandler):
    def handle(self):
        established = False
        try:
            headers, initial = read_request(self.request)
            host, port = parse_request(headers)
            with connect_target(host, port) as upstream:
                self.request.sendall(b'HTTP/1.1 200 Connection Established\r\n\r\n')
                established = True
                tunnel(self.request, upstream, initial)
        except RequestError as error:
            send_error(self.request, error.status)
        except PolicyError:
            send_error(self.request, 403)
        except TimeoutError:
            if not established:
                send_error(self.request, 408)
        except OSError:
            if not established:
                send_error(self.request, 502)


class ProxyServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 32

    def __init__(self, address):
        self.slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
        super().__init__(address, ConnectHandler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            send_error(request, 503)
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        # Deliberately suppress socketserver's traceback/request logging.
        pass


if __name__ == '__main__':
    with ProxyServer(('0.0.0.0', PORT)) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
