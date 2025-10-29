# src/common.py
import socket
import json

def send_ipc_command(socket_path, command):
    """

    Connects to the Unix Domain Socket, sends a JSON command,
    and returns the JSON response.
    """
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(socket_path)
        
        # Encode the command dictionary as JSON and then as bytes
        message = json.dumps(command).encode('utf-8')
        sock.sendall(message)
        
        # Receive the response
        response_bytes = sock.recv(4096)
        if not response_bytes:
            return None
            
        # Decode the bytes to a string and then parse the JSON
        response = json.loads(response_bytes.decode('utf-8'))
        return response
        
    finally:
        sock.close()
