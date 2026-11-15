"""Startup ports: launcher/server agreement and real occupied-socket fallback."""
import errno
import socket
import unittest
from unittest.mock import patch
import launch
from sowscout.web.server import make_available_server, make_server
from .helpers import temp_settings

class TestStartupPorts(unittest.TestCase):
    def test_launcher_passes_default_to_child(self):
        port, args = launch.prepare_ui_args(["--open"])
        self.assertEqual(port, 8767)
        self.assertEqual(args, ["--open", "--port", "8767"])

    def test_both_port_syntaxes_and_os_assignment(self):
        for args, expected in [(["--port", "8771"], 8771), (["--port=8772"], 8772), (["--port=0"], 0)]:
            port, child = launch.prepare_ui_args(args + ["--provider", "mock"])
            self.assertEqual(port, expected)
            self.assertEqual(child, ["--provider", "mock", "--port", str(expected)])

    def test_occupied_port_is_not_shared(self):
        settings = temp_settings()
        first = make_server("127.0.0.1", 0, settings)
        self.addCleanup(first.server_close)
        port = first.server_address[1]
        with self.assertRaises(OSError):
            duplicate = make_server("127.0.0.1", port, settings)
            duplicate.server_close()
        second = make_available_server("127.0.0.1", port, settings)
        self.addCleanup(second.server_close)
        self.assertGreater(second.server_address[1], port)

    def test_port_zero_uses_os_assigned_socket(self):
        server = make_available_server("127.0.0.1", 0, temp_settings())
        self.addCleanup(server.server_close)
        self.assertGreater(server.server_address[1], 0)

    def test_invalid_ports(self):
        for port in [-1, 65536]:
            with self.assertRaises(ValueError):
                make_available_server(port=port)

    def test_unrelated_network_error_is_not_hidden(self):
        with patch("sowscout.web.server.make_server", side_effect=OSError(errno.EADDRNOTAVAIL, "bad host")) as create:
            with self.assertRaises(OSError):
                make_available_server()
            self.assertEqual(create.call_count, 1)

    def test_retry_exhaustion_is_bounded(self):
        with patch("sowscout.web.server.make_server", side_effect=OSError(errno.EADDRINUSE, "busy")) as create:
            with self.assertRaises(OSError):
                make_available_server(port=65534)
            self.assertEqual(create.call_count, 2)
