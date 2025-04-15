import socket
import threading
import time
import uuid


class Peer:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.connections = []  # list of (conn, addr)
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.seen_messages = set()  # to prevent loops

    def connect(self, peer_host, peer_port):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((peer_host, peer_port))
            self.connections.append((s, (peer_host, peer_port)))
            threading.Thread(target=self.handle_connection, args=(s,), daemon=True).start()
            print(f"Connected to {peer_host}:{peer_port}")
        except socket.error as e:
            print(f"Failed to connect to {peer_host}:{peer_port}. Error: {e}")

    def listen(self):
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(10)
        print(f"Listening for connections on {self.host}:{self.port}")

        while True:
            conn, addr = self.server_socket.accept()
            self.connections.append((conn, addr))
            print(f"Accepted connection from {addr}")
            threading.Thread(target=self.handle_connection, args=(conn,), daemon=True).start()

    def handle_connection(self, conn):
        while True:
            try:
                data = conn.recv(1024)
                if not data:
                    break
                message = data.decode()
                msg_id, msg_text = message.split(";", 1)

                if msg_id not in self.seen_messages:
                    self.seen_messages.add(msg_id)
                    print(f"Received: {msg_text}")
                    self.flood_message(msg_id, msg_text, exclude_conn=conn)
            except Exception as e:
                print(f"Error in receiving: {e}")
                break

    def send_data(self, msg_text):
        msg_id = str(uuid.uuid4())
        message = f"{msg_id};{msg_text}"
        self.seen_messages.add(msg_id)
        self.flood_message(msg_id, msg_text)

    def flood_message(self, msg_id, msg_text, exclude_conn=None):
        message = f"{msg_id};{msg_text}"
        for conn, _ in self.connections:
            if conn != exclude_conn:
                try:
                    conn.sendall(message.encode())
                except socket.error as e:
                    print(f"Failed to send data. Error: {e}")

    def start(self):
        listen_thread = threading.Thread(target=self.listen, daemon=True)
        listen_thread.start()
