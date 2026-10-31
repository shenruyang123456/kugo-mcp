import json
import time
import unittest
import io
from types import SimpleNamespace
from unittest.mock import patch
from kugo_mcp.native import NativeClient


class Socket:
    def __init__(self):
        self.messages = []
        self.sent = []
        self.closed = False

    def settimeout(self, timeout): self.timeout = timeout

    def send(self, data):
        request = json.loads(data)
        self.sent.append(request)
        expression = request['params'].get('expression', '')
        if expression.startswith('window.__kugoMcpBridge.begin('):
            job, action, _ = json.loads('[' + expression.split('(', 1)[1][:-1] + ']')
            self.messages.append({'method': 'Runtime.bindingCalled', 'params': {
                'name': '__kugoMcpResult', 'payload': json.dumps({'id': job, 'result': {'accepted': True}})}})
        self.messages.append({'id': request['id'], 'result': {'result': {'value': True}}})

    def recv(self): return json.dumps(self.messages.pop(0))
    def shutdown(self): self.closed = True


class TransportTests(unittest.TestCase):
    def test_reuses_socket_and_handles_result_before_ack(self):
        client = NativeClient()
        client.ws = Socket()
        for action in ('pause', 'play'):
            self.assertTrue(client.request(action)['accepted'])
        self.assertEqual(len(client.ws.sent), 2)

    def test_expired_command_is_never_sent(self):
        client = NativeClient()
        connection = client.ws = Socket()
        with self.assertRaises(TimeoutError): client.request('next', time.monotonic() - 1)
        self.assertEqual(connection.sent, [])
        self.assertTrue(connection.closed)

    def test_failed_command_is_not_retried(self):
        client = NativeClient()
        connection = client.ws = Socket()
        with patch.object(connection, 'recv', side_effect=TimeoutError):
            with self.assertRaises(TimeoutError): client.request('next')
        self.assertEqual(len(connection.sent), 1)

    def test_snapshot_retains_real_hash_and_position(self):
        client = NativeClient()
        with patch.object(client, 'request', return_value={'hash': 'real-hash', 'duration_ms': 20000, 'progress': '123450000'}):
            song, position = client.snapshot()
        self.assertEqual(song['hash'], 'real-hash')
        self.assertEqual(position, 12345)

    def test_loading_page_does_not_install_or_call_native_bridge(self):
        class LoadingSocket(Socket):
            def send(self, data):
                request = json.loads(data)
                self.sent.append(request)
                self.messages.append({'id': request['id'], 'result': {'result': {'value': False}}})
        connection = LoadingSocket()
        targets = [{'type': 'page', 'url': 'https://pc.service.kugou.com/yueku/2024/find/index.html',
                    'webSocketDebuggerUrl': 'ws://127.0.0.1:9225/devtools/page/test'}]
        opener = SimpleNamespace(open=lambda *a, **kw: io.StringIO(json.dumps(targets)))
        client = NativeClient()
        with patch('kugo_mcp.native.build_opener', return_value=opener), patch('kugo_mcp.native.websocket.create_connection', return_value=connection):
            with self.assertRaises(RuntimeError):
                client.request('snapshot')
        self.assertEqual(len(connection.sent), 1)
        self.assertEqual(connection.sent[0]['method'], 'Runtime.evaluate')
        self.assertNotIn('SuperCall', connection.sent[0]['params']['expression'])
        self.assertEqual(client.phase, 'page_ready')
        self.assertTrue(connection.closed)
