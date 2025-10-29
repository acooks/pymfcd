# tests/test_common.py
import pytest
import socket
import os
import json
import threading
import time

from src.common import send_ipc_command

def echo_server(socket_path, server_ready_event):
    """A simple server that listens, accepts one connection, echoes, and exits."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(socket_path)
    sock.listen(1)
    server_ready_event.set() # Signal that the server is ready

    conn, _ = sock.accept()
    with conn:
        data = conn.recv(1024)
        if data:
            conn.sendall(data)
    sock.close()

def test_ipc_send_and_receive(tmp_path):
    """
    Tests the basic send_ipc_command function against a simple echo server.
    """
    socket_path = str(tmp_path / "test_socket.sock") # Convert Path to string
    server_ready_event = threading.Event()

    server_thread = threading.Thread(target=echo_server, args=(socket_path, server_ready_event))
    server_thread.start()

    # Wait for the server to be ready before the client tries to connect
    server_ready_event.wait(timeout=1)
    assert server_ready_event.is_set(), "Server did not start in time"

    test_command = {"action": "TEST", "payload": "hello"}
    response = send_ipc_command(socket_path, test_command)

    assert response == test_command

    server_thread.join(timeout=1)
    assert not server_thread.is_alive(), "Server thread did not terminate"
