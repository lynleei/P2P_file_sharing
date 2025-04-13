import socket
import threading

# Peer class that will represent each node in the network. 
# This class will handle creating and managing connections with peers and exchanging data.
class Peer:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connections = []

    # Method to create connections with other peers.
    def connect(self, peer_host, peer_port):
        try:
            connection = self.socket.connect((peer_host, peer_port))
            self.connections.append(connection)
            print(f"Connected to {peer_host}:{peer_port}")
        except socket.error as e:
            print(f"Failed to connect to {peer_host}:{peer_port}. Error: {e}")

    # Listen method to accept incoming connections from other peers.
    def listen(self):
        self.socket.bind((self.host, self.port))
        self.socket.listen(10)
        print(f"Listening for connections on {self.host}:{self.port}")

        while True:
            connection, address = self.socket.accept()
            self.connections.append(connection)
            print(f"Accepted connection from {address}")

    # Data exchange method to send and receive data from connected peers.
    def send_data(self, data):
        for connection in self.connections:
            try:
                connection.sendall(data.encode())
            except socket.error as e:
                print(f"Failed to send data. Error: {e}")

    # start listening thread
    def start(self):
        listen_thread = threading.Thread(target=self.listen)
        listen_thread.start()

    def main():
        print('"')
    if __name__ == "__main__":
        main()
