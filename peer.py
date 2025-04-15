import socket
import threading
import time
import uuid


class Peer:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.connections = []
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.seen = set()
        self.shareFile = list()
        self.request = list()

    def connect(self, peer_host, peer_port):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((peer_host, peer_port))
            self.connections.append(s)
            print(f"Connected to {peer_host}:{peer_port}")
        except socket.error as e:
            print(f"Failed to connect to {peer_host}:{peer_port}. Error: {e}")

    def listen(self):
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(10)
        print(f"Listening for connections on {self.host}:{self.port}")

        while True:
            conn, addr = self.server_socket.accept()
            self.connections.append(conn)
            print(f"Accepted connection from {addr}")
            threading.Thread(target=self.receive_connection, args=(conn,), daemon=True).start()

    def receive_connection(self, conn):
        while True:
            try:
                data = conn.recv(1024)
                if not data:
                    break
                message = data.decode()
                msg_part = message.split(";")

                if msg_part[0] not in self.seen:
                    self.seen.add(msg_part[0])
                    print(f"Received: {msg_part[1]}")
                    if msg_part[4] == "file_request":
                        if msg_part[1] in self.shareFile:
                            self.send_direct_message(msg_part[2], msg_part[3])
                        else:
                            self.flood(message, exclude_conn=conn)

                    elif msg_part[4] == "file_response":
                        print(msg_part)
                        self.request.remove(msg_part[1])
                        # perform download stuff

            except Exception as e:
                print(f"Error in receiving: {e}")
                break

    def send_direct_message(self, host, port, filename):
        id = str(uuid.uuid4())
        msg = f"{id};{filename};{self.host};{self.port};file_response"
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((host, port))
            s.sendall(msg.encode())
            s.close()
        except Exception as e:
            print(f"Direct send to {host}:{port} failed: {e}")

    def flood(self, message, exclude_conn=None):
        for conn in self.connections:
            if conn != exclude_conn:
                try:
                    conn.sendall(message.encode())
                except socket.error as e:
                    print(f"Failed to send data. Error: {e}")

    def send_data(self, data):
        self.request.append(data)
        id = str(uuid.uuid4())
        msg = f"{id};{data};{self.host};{self.port};file_request"
        for conn in self.connections:
            try:
                conn.sendall(msg.encode())
            except socket.error as e:
                print(f"Failed to send data. Error: {e}")

    def start(self):
        listen_thread = threading.Thread(target=self.listen, daemon=True)
        listen_thread.start()

    def request_download(self):
        self.send_direct_message()


def main():
    peer1 = Peer("127.0.0.1", 5000)
    peer1.start()

    time.sleep(1)  # give time for the server to start

    peer2 = Peer("127.0.0.1", 6000)
    peer2.start()
    peer2.connect("127.0.0.1", 5000)

    peer1.connect("127.0.0.1", 6000)

    time.sleep(1)  # give time to connect
    peer2.send_data("Hello from Peer 2!")

    while True:
        pass


if __name__ == "__main__":
    main()
