import socket
import threading
import time


class Peer:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.connections = []
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

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

    def send_data(self, data):
        for conn in self.connections:
            try:
                conn.sendall(data.encode())
            except socket.error as e:
                print(f"Failed to send data. Error: {e}")

    def start(self):        
        listen_thread = threading.Thread(target=self.listen, daemon=True)
        listen_thread.start()


def main():
    peer1 = Peer("127.0.0.1", 5000)
    peer1.start()

    time.sleep(1)  # give time for the server to start

    peer2 = Peer("127.0.0.1", 6000)
    peer2.start()
    peer2.connect("127.0.0.1", 5000)

    time.sleep(1)  # give time to connect

    peer2.send_data("Hello from Peer 2!")
    peer1.send_data("Hello back from Peer 1!")
if __name__ == "__main__":
    main()
