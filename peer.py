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
        print(f"[INDEX] shareFile updated: {self.shareFile}")

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
            
            print(f"{self.port}: [DIAL] → {ip}:{port}")
        except Exception as e:
            print(f"Connection failed: {e}")

    # ───────── flooding helper ─────────
    def flood(self, msg: str, exclude_conn=None):
        for c in self.connections:
            if c is exclude_conn: 
                continue
            else:
                try: 
                    c.sendall(msg.encode())
                except: 
                    pass

    # ───────── main per‑connection loop ─────────
    def receive_connection(self, conn):
        while True:
            try:
                raw = conn.recv(4096)
                if not raw: 
                    break
                parts = raw.decode(errors="ignore").split(";")
                if len(parts) < 5: 
                    continue

                mid, payload, phost, pport, mtype = parts[:5]
                                                       # pport is a string
                peer_addr = (phost, int(pport))
                if peer_addr != (self.host, self.port):     # don’t add myself
                    self.known_peers.add(peer_addr)

            except ValueError:
                pass
                if mid in self.seen: 
                    continue

                self.seen.add(mid)
                print(f"[RX] {mtype:14} | {payload}")

                if mtype == "ping":
                    self.handle_ping(conn)

                elif mtype == "pong":
                    self.handle_pong(payload)

                elif mtype == "list_request":
                    self._handle_list_request(conn)

                elif mtype == "list_response":
                    self._handle_list_response(payload)

                elif mtype == "download_request":
                    if len(parts) > 5:
                        self.handle_download_request(conn, parts[5])

                elif mtype == "download_ready":
                    if len(parts) > 6:
                        self.handle_download_ready(conn, parts[5], parts[6], parts[7])

            except Exception as e:
                print("[ERR ] recv:", e)
                break

    # ───────── peer discovery ─────────
    def ping_peers(self):
        mid = str(uuid.uuid4())
        self.flood(f"{mid};{list(self.known_peers)};{self.host};{self.port};ping")

    def handle_ping(self, conn):
        mid = str(uuid.uuid4())
        conn.sendall(f"{mid};{list(self.known_peers)};{self.host};{self.port};pong".encode())

    def handle_pong(self, payload):
        try:
            for p in eval(payload):
                self.known_peers.add(tuple(p))
            print("[DISC] peers →", self.known_peers)
        except: 
            pass

    # ───────── list / index ─────────
    def list_files(self):
        mid = str(uuid.uuid4())
        self.flood(f"{mid};ASK;{self.host};{self.port};list_request")

    def _handle_list_request(self, conn):
        mid = str(uuid.uuid4())
        listing = "|".join(self.shareFile)
        conn.sendall(f"{mid};{listing};{self.host};{self.port};list_response".encode())

    def _handle_list_response(self, listing):
        for f in listing.split("|"):
            if f and f not in self.shareFile: 
                self.shareFile.append(f)
        print("[INDEX] shareFile updated:", self.shareFile)

    # ───────── download logic ─────────
    def request_file(self, fname):
        mid = str(uuid.uuid4())
        self.flood(f"{mid};-;{self.host};{self.port};download_request;{fname}")

    def handle_download_request(self, conn, fname):
        path = os.path.join(self.shared_dir, fname)
        if not os.path.isfile(path): 
            return
            
        file_size = os.path.getsize(path)
        file_hash = self._compute_sha256(path)
        mid = str(uuid.uuid4())
        header = f"{mid};ready;{self.host};{self.port};download_ready;{fname};{file_hash};{file_size}"
        conn.sendall(header.encode())
        
        with open(path, "rb") as f:
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk: 
                    break
                conn.sendall(chunk)
        print(f"[SEND] {fname}")

    def handle_download_ready(self, conn, fname, expected_hash, file_size):
        try:
            file_size = int(file_size)
            os.makedirs("downloads", exist_ok=True)
            dest = os.path.join("downloads", fname)
            
            received = 0
            with open(dest, "wb") as f:
                while received < file_size:
                    chunk = conn.recv(min(CHUNK_SIZE, file_size - received))
                    if not chunk: 
                        break
                    f.write(chunk)
                    received += len(chunk)
            
            actual_hash = self._compute_sha256(dest)
            if actual_hash == expected_hash:
                print(f"[GET ] {fname} OK")
                self.shareFile.append(fname)
            else:
                print(f"[GET ] {fname} BAD HASH")
                os.remove(dest)
        except Exception as e:
            print(f"[ERR ] Download failed: {e}")

    # ───────── SHA‑256 helper ─────────
    @staticmethod
    def _compute_sha256(path):
        h = hashlib.sha256()
        with open(path,"rb") as f:
            for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
                h.update(chunk)
        return h.hexdigest()

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

    active = p1
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
            elif op == "ping": 
                active.ping_peers()

            elif op == "peers":
                print("Known peers:", active.known_peers)
            
            elif op == "list":
                active.list_files()
            
            elif op == "showfiles":
                print("Shared files:", active.shareFile)
            
            elif op == "say" and len(cmd) > 1:
                active.flood(" ".join(cmd[1:]))
            
            elif op == "get" and len(cmd) == 2:
                active.request_file(cmd[1])
            
            elif op == "exit":
                break
            
            else:
                print("Unknown command")
        
        except (KeyboardInterrupt, EOFError):
            break

if __name__ == "__main__":
    main()