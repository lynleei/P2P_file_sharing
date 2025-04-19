#!/usr/bin/env python3
import socket
import threading
import time
import uuid
import os
import hashlib

CHUNK_SIZE = 1024                      # bytes per chunk

class Peer:
    def __init__(self, host, port, shared_dir):
        self.host, self.port = host, port
        self.server_socket   = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connections: list[socket.socket]     = []
        self.known_peers: set[tuple[str,int]]     = set()
        self.seen: set[str]                       = set()
        self.shareFile: list[str]                 = []   # filenames to share
        self.request:   list[str]                 = []   # outstanding requests
        self.shared_dir = "shared"
        os.makedirs(self.shared_dir, exist_ok=True)
        self._index_files()  # Auto-index shared files
        self.scan_shared(shared_dir)

    def scan_shared(self, directory: str = None):
        target_dir = directory or self.shared_dir
        try:
            entries = os.listdir(target_dir)
        except OSError as e:
            print(f"[ERR ] cannot list directory {target_dir}: {e}")
            return

        files = []
        for name in entries:
            path = os.path.join(target_dir, name)
            if os.path.isfile(path):
                files.append(name)

        self.shareFile = files
        #print(f"[INDEX] shareFile updated: {self.shareFile}")

    def _index_files(self):
        """Refresh list of available files from shared directory"""
        self.shareFile = [f for f in os.listdir(self.shared_dir)
                         if os.path.isfile(os.path.join(self.shared_dir, f))]

    # ───────── listener / connector ─────────
    def start(self):
        threading.Thread(target=self._listen_loop, daemon=True).start()

    def _listen_loop(self):
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(10)
        #print(f"[LISTEN] {self.host}:{self.port}")
        while True:
            conn, addr = self.server_socket.accept()
            self.connections.append(conn); 
            #self.known_peers.add(addr)
            threading.Thread(target=self.receive_connection,
                             args=(conn,), daemon=True).start()

    def connect(self, ip, port):
        try:
            s = socket.socket()
            s.connect((ip, port))
            self.connections.append(s)
            self.known_peers.add((ip, port))
            
            #print(f"{self.port}: [DIAL] → {ip}:{port}")
        except Exception as e:
            print(f"Connection failed: {e}")

    # ───────── main per‑connection loop ─────────
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
                    print(f"{self.port}: Received: {msg_part[1]}, {msg_part[4]}")
                    if msg_part[4] == "file_request":
                        # verify if I have this file, If I do, then send file to sender, else flood
                        if msg_part[1] in self.shareFile:
                            self.send_direct_message()
                        else:
                            self.flood(message, exclude_conn=conn)
                    elif msg_part[4] == "file_response":
                        pass

            except Exception as e:
                print(f"Error in receiving: {e}")
                break


    # ───────── SHA‑256 helper ─────────

    @staticmethod
    def _compute_sha256(path):
        h = hashlib.sha256()
        with open(path,"rb") as f:
            for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
                h.update(chunk)
        return h.hexdigest()

    def send_data(self, filename):
        id = str(uuid.uuid4())
        msg = f"{id};{filename};{self.host};{self.port};file_request"
        for conn in self.connections:
            try:
                conn.sendall(msg.encode())
            except socket.error as e:
                print(f"Failed to send data. Error: {e}")

    def flood(self, message, exclude_conn=None):
        for conn in self.connections:
            if conn != exclude_conn:
                try:
                    conn.sendall(message.encode())
                except socket.error as e:
                    print(f"Failed to send data. Error: {e}")

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

# ─────────────────── CLI ────────────────────
def main():
    p1 = Peer("127.0.0.1", 5000, "shared\p1")
    p1.start()

    p2 = Peer("127.0.0.1", 6000, "shared\p2")
    p2.start()

    p3 = Peer("127.0.0.1", 7000, "shared\p3")
    p3.start()

    p4 = Peer("127.0.0.1", 8000, "shared\p4")
    p4.start()

    p5 = Peer("127.0.0.1", 9000, "shared\p5")
    p5.start()

    # Connect peers to each other
    p2.connect("127.0.0.1", 5000)
    p1.connect("127.0.0.1", 6000)

    p3.connect("127.0.0.1", 5000)
    p1.connect("127.0.0.1", 7000)

    p4.connect("127.0.0.1", 6000)
    p2.connect("127.0.0.1", 8000)

    p5.connect("127.0.0.1", 6000)
    p2.connect("127.0.0.1", 9000)

    active = p2
    print("Type 'help' for commands.")

    while True:
        try:
            cmd = input(">>> ").split()
            if not cmd: 
                continue
            op = cmd[0].lower()

            if op == "help":
                print("""Commands:
    ping       - Discover peers
    peers      - Show known peers
    list       - List available files
    showfiles  - Show shared files
    get <file> - Download file
    say <msg>  - Broadcast message
    exit       - Quit""")

            elif op == "peers":
                print("Known peers:", active.known_peers)
            
            elif op == "showfiles":
                print("Shared files:", active.shareFile)

            elif op == "get" and len(cmd) == 2:
                active.send_data(cmd[1])
            
            elif op == "exit":
                break
            
            else:
                print("Unknown command")
        
        except (KeyboardInterrupt, EOFError):
            break

if __name__ == "__main__":
    main()