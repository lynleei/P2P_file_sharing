import socket
import threading
import time
import uuid
import os
import json
import hashlib

CHUNK_SIZE = 1024  # Size of each chunk to be sent over the network (need for chunked file transfer)

class Peer:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.connections = []   # list of active sockets
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.seen = set()       # track the message IDs we've already processed/flooded
        self.shareFile = []     # list of files to share
        self.request = []       # list of requests to send

        # Set of discovered peer addresses for "Peer Discovery"
        self.known_peers = set()

        # Create a local shared directory
        self.shared_dir = "shared"
        os.makedirs(self.shared_dir, exist_ok = True)

    def connect(self, peer_host, peer_port):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((peer_host, peer_port))
            self.connections.append(s)
            print(f"Connected to {peer_host}:{peer_port}")
        except socket.error as e:
            print(f"Failed to connect to {peer_host}:{peer_port}. Error: {e}")

    # -------------------------------------
    # Multithreading and concurrency stuff should go here
    # -------------------------------------
    def start(self):
        """
        Background thread to listen for incoming connections.
        """
        listen_thread = threading.Thread(target=self.listen, daemon=True)
        listen_thread.start()

    def listen(self):
        """
        Bind and listen for incoming connections on self.host:self.port.
        Use loop to accept connections and send to receive_connection.
        """
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(10)
        print(f"Listening for connections on {self.host}:{self.port}")

        while True:
            conn, addr = self.server_socket.accept()
            self.connections.append(conn)
            self.known_peers.add(addr)  # Add to known peers
            print(f"Accepted connection from {addr}")
            threading.Thread(target=self.receive_connection, args=(conn,), daemon=True).start()

    # --------------------------------------------------------------------------------
    # this is probably the part where we implement the concurrency of file transfers
    # also need to handle ping pong here
    # --------------------------------------------------------------------------------
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
                    print(f"Received: {msg_part[1]}, {msg_part[4]}")
                    if msg_part[4] == "file_request":
                        if msg_part[1] in self.shareFile:
                             self.send_direct_message(msg_part[2], msg_part[3])
                             self.send_direct_message(msg_part[2], msg_part[3], msg_part[1])
                        else:
                             self.flood(message, exclude_conn=conn)
 
                    elif msg_part[4] == "file_response":
                         print(msg_part)
                         self.request.remove(msg_part[1])
                         # perform download stuff
 
            except Exception as e:
                 print(f"Error in receiving: {e}")
                 break
            
    # -------------------------------------
    # Peer Discovery (ping/pong)
    # -------------------------------------
    def ping_peers(self):
        """
        Probing a peer to see if they're alive
        Send a "ping" semicolon message to all peers. 
        Embed known_peers in the payload if we want them to discover each other.
        """
        msg_id = str(uuid.uuid4())
        known_peers_str = str(list(self.known_peers))
        # Format: "msg_id;payload;host;port;type"
        # We'll place known_peers_str in 'payload'
        msg = f"{msg_id};{known_peers_str};{self.host};{self.port};ping"
        self._flood(msg)

    def handle_ping(self, conn, msg_id, msg_host, msg_port):
        """
        A reply to a Ping
        Upon receiving 'ping', respond with 'pong' containing our known_peers.
        """
        pong_id = str(uuid.uuid4())
        # Add known_peers in the payload
        peers_payload = str(list(self.known_peers))
        resp = f"{pong_id};{peers_payload};{self.host};{self.port};pong"
        conn.sendall(resp.encode())

    def handle_pong(self, payload):
        """
        Update known_peers set based on the payload we get from a pong.
        The payload is str(list_of_peers).
        """
        try:
            # Evaluate the string like "[(ip1, port1), (ip2, port2)]"
            new_peers = eval(payload)
            for p in new_peers:
                self.known_peers.add(tuple(p))
            print(f"[DISCOVERY] Updated known peers: {self.known_peers}")
        except:
            pass

    def send_direct_message(self, host, port, filename):
        id = str(uuid.uuid4())
        msg = f"{id};{filename};{self.host};{self.port};file_response"
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((host, int(port)))
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

    def flood_json(self, message, exclude_conn=None):
         """
        Flood a JSON-based message (dict) to all peers except exclude_conn.
        ----> dont necessarily have to incorporate json so can do without but will need to modify chunked file transfer
        """
         pass

    def send_data(self, data):
        """
        This function creates a semicolon-delimited message for data (filename)
        and floods it as 'file_request' to all peers.
        """
        id = str(uuid.uuid4())
        msg = f"{id};{data};{self.host};{self.port};file_request"
        for conn in self.connections:
            try:
                conn.sendall(msg.encode())
            except socket.error as e:
                print(f"Failed to send data. Error: {e}")

    # -------------------------------------
    # Chunked file transfer
    # -------------------------------------
    def request_file(self, filename):
        """
        Ask the network for a file.
        We just flood a "DOWNLOAD_REQUEST" in hopes that a peer with the file responds.
        """
        msg_id = str(uuid.uuid4())
        msg = f"{msg_id};REQUESTING_FILE;{self.host};{self.port};download_request;{filename}"
        self.flood(msg)

    # Once we hae the file we want to either say download ready and send file chunks
    # Otherwise ignore and send error
    def download_request(self, conn, addr, filename):
        """
        If we have the requested file, respond with "DOWNLOAD_READY" and then send the chunks.
        Otherwise, we might just ignore or send an error.
        """
        if not filename:
            err_id = str(uuid.uuid4())
            err_msg = f"{err_id};No filename specified.;{self.host};{self.port};error"
            conn.sendall(err_msg.encode())
            return

        file_path = os.path.join(self.shared_dir, filename)
        if not os.path.isfile(file_path):
            err_id = str(uuid.uuid4())
            err_msg = f"{err_id};File '{filename}' not found.;{self.host};{self.port};error"
            conn.sendall(err_msg.encode())
            return

        # Compute file hash for integrity check
        fhash = self._compute_sha256(file_path)

        ready_id = str(uuid.uuid4())
        ready_msg = f"{ready_id};SENDING_FILE;{self.host};{self.port};download_ready;{filename};{fhash}"
        conn.sendall(ready_msg.encode())

        # Send the file in CHUNK_SIZE chunks
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                conn.sendall(chunk)

        print(f"[INFO] Sent file '{filename}' to {addr}")

    def receive_file(self, conn, filename, expected_hash):
        """
        Receive file chunks from 'conn' and save them locally in 'downloads'.
        Then compute hash to verify integrity if 'expected_hash' is provided.
        """
        downloads_dir = "downloads"
        os.makedirs(downloads_dir, exist_ok=True)
        out_path = os.path.join(downloads_dir, filename)
        print(f"[INFO] Receiving file '{filename}' -> {out_path}")

        with open(out_path, "wb") as f:
            while True:
                chunk = conn.recv(CHUNK_SIZE)
                if not chunk:
                    break
                f.write(chunk)

        # Integrity check -- checksum
        if expected_hash:
            actual_hash = self._compute_sha256(out_path)
            if actual_hash == expected_hash:
                print(f"[INFO] File '{filename}' verified successfully (SHA-256).")
            else:
                print(f"[ERROR] Integrity check failed! Expected {expected_hash}, got {actual_hash}.")
        else:
            print("[WARN] No hash provided; skipping integrity check.")
    
    # -------------------------------------
    # Verifying File Integrity -- Checksum
    # -------------------------------------
    def _compute_sha256(self, file_path):
        """
        Compute a SHA-256 hash for the file at 'file_path'.
        """
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                hasher.update(chunk)
        return hasher.hexdigest()
        

def main():
    peer1 = Peer("127.0.0.1", 5000)
    peer1.shareFile = ["file1.txt"]
    peer1.start()

    time.sleep(1)  # give time for the server to start

    peer2 = Peer("127.0.0.1", 6000)
    peer2.start()
    peer2.connect("127.0.0.1", 5000)

    peer1.connect("127.0.0.1", 6000)

    time.sleep(1)  # give time to connect
    peer2.send_data("file1.txt")

    while True:
        pass


if __name__ == "__main__":
    main()