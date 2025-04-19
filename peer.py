#!/usr/bin/env python3

import socket 
import threading
import time
import uuid
import os
import hashlib

CHUNK_SIZE = 1024  # bytes per chunk

class Peer:
    def __init__(self, host, port, shared_dir):
        self.host, self.port = host, port
        self.server_socket   = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connections     = []               # active sockets
        self.known_peers     = set()            # discovered (ip,port)
        self.seen            = set()            # seen message IDs
        self.shareFile       = []               # local files
        self.request         = []               # outstanding requests
        self.shared_dir      = shared_dir
        os.makedirs(self.shared_dir, exist_ok=True)

        # index whatever's already in shared_dir
        self.scan_shared()

    def scan_shared(self):
        """Scan self.shared_dir and populate self.shareFile."""
        self.shareFile = [
            f for f in os.listdir(self.shared_dir)
            if os.path.isfile(os.path.join(self.shared_dir, f))
        ]

    # ────────── networking ──────────
    def start(self):
        threading.Thread(target=self._listen_loop, daemon=True).start()

    def _listen_loop(self):
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(10)
        
        while True:
            conn, addr = self.server_socket.accept()
            self.connections.append(conn)
            threading.Thread(target=self.receive_connection,
                             args=(conn,), daemon=True).start()

    def connect(self, ip, port):
        try:
            s = socket.socket()
            s.connect((ip, port))
            self.connections.append(s)
            self.known_peers.add((ip, port))
        except Exception as e:
            print(f"[ERR] {ip}:{port} failed: {e}")

    def flood(self, msg, exclude_conn=None):
        for c in self.connections:
            if c is exclude_conn:
                continue
            try:
                c.sendall(msg.encode())
            except:
                pass

    # ────────── message loop ──────────
    def receive_connection(self, conn):
        while True:
            try:
                data = conn.recv(4096)
                if not data:
                    break
                parts = data.decode().split(";")
                if len(parts) < 5:
                    continue

                mid, payload, ph, pport, msg_type = parts[:5]

                if mid in self.seen:
                    continue
                self.seen.add(mid)

                print(f"[{self.port}] RX {msg_type:14} | {payload}")

                # 1) A peer flooding a file_request?
                if msg_type == "file_request":
                    fname = payload
                    if fname in self.shareFile:
                        # I have it: reply with file_response
                        self.send_direct_message(ph, int(pport), fname, "file_response")
                    else:
                        # otherwise keep flooding
                        self.flood(data.decode(), exclude_conn=conn)

                # 2) A peer telling me they have it?
                elif msg_type == "file_response":
                    fname = payload
                    if fname in self.request:
                        self.request.remove(fname)
                        threading.Thread(
                        target=self.download_file,
                        args=(ph, int(pport), fname),
                        daemon=True
                    ).start()
    

                # 3) A peer directly asking to download
                elif msg_type == "download_request":
                    fname = parts[5]
                    self.handle_download_request(conn, fname)

                # 4) A peer sending chunks + header
                elif msg_type == "download_ready":
                    fname, exp_hash, size = parts[5], parts[6], parts[7]
                    threading.Thread(
                        target=self.handle_download_ready,
                        args=(conn, fname, exp_hash, size),
                        daemon=True
                    ).start()

            except Exception as e:
                print(f"[ERR] recv: {e}")
                break

    # ────────── file transfer ──────────
    def request_file(self, fname):
        self.request.append(fname)
        mid = str(uuid.uuid4())
        self.flood(f"{mid};{fname};{self.host};{self.port};file_request")

    def handle_download_request(self, conn, fname):
        path = os.path.join(self.shared_dir, fname)
        if not os.path.isfile(path):
            return
        size = os.path.getsize(path)
        sha  = self._compute_sha256(path)
        mid  = str(uuid.uuid4())
        header = (
            f"{mid};ready;{self.host};{self.port};"
            f"download_ready;{fname};{sha};{size}"
        )
        conn.sendall(header.encode())
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
                conn.sendall(chunk)
        print(f"[{self.port}] SEND {fname}")

    def handle_download_ready(self, conn, fname, expected_hash, file_size):
        try:
            total = int(file_size)
            os.makedirs("downloads", exist_ok=True)
            dest = os.path.join("downloads", fname)

            recvd = 0
            with open(dest, "wb") as f:
                while recvd < total:
                    chunk = conn.recv(min(CHUNK_SIZE, total - recvd))
                    if not chunk:
                        break
                    f.write(chunk)
                    recvd += len(chunk)

            actual = self._compute_sha256(dest)
            if actual == expected_hash:
                print(f"[{self.port}] GET {fname} OK")
                self.shareFile.append(fname)
            else:
                print(f"[{self.port}] GET {fname} BAD")
                os.remove(dest)

        except Exception as e:
            print(f"[ERR] download: {e}")

    @staticmethod
    def _compute_sha256(path):
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for c in iter(lambda: f.read(CHUNK_SIZE), b""):
                h.update(c)
        return h.hexdigest()

    # ────────── helper to send direct replies ──────────
    def send_direct_message(self, host, port, fname, mtype):
        mid = str(uuid.uuid4())
        msg = f"{mid};{fname};{self.host};{self.port};{mtype}"
        try:
            s = socket.socket(); s.connect((host, port))
            s.sendall(msg.encode()); s.close()
            
        except Exception as e:
            print(f"[ERR] direct→{host}:{port}: {e}")

    def download_file(self, peer_host: str, peer_port: int, filename: str, save_as: str = None):
        """
        Connects directly to the peer at (peer_host, peer_port),
        sends a download request, receives the file in chunks,
        and verifies it against the SHA-256 hash.
        """
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((peer_host, peer_port))

            # 1) Send a download_request packet
            mid = str(uuid.uuid4())
            req = f"{mid};-;{self.host};{self.port};download_request;{filename}"
            s.sendall(req.encode())

            # 2) Read the header response (download_ready)
            header = s.recv(4096).decode().split(";")
            # header == [ mid, "ready", peer_host, peer_port, "download_ready", fname, file_hash, file_size ]
            if len(header) < 8 or header[4] != "download_ready":
                print(f"[{self.port}] Unexpected header: {header}")
                s.close()
                return

            _, _, _, _, _, fname, expected_hash, size_str = header
            total_size = int(size_str)

            # 3) Stream in the file chunks
            os.makedirs("downloads", exist_ok=True)
            dest = save_as or fname
            dest = os.path.join("downloads", dest)
            received = 0
            sha256 = hashlib.sha256()

            with open(dest, "wb") as f:
                while received < total_size:
                    chunk = s.recv(min(CHUNK_SIZE, total_size - received))
                    if not chunk:
                        break
                    f.write(chunk)
                    sha256.update(chunk)
                    received += len(chunk)

            s.close()

            # 4) Verify integrity
            actual_hash = sha256.hexdigest()
            if actual_hash == expected_hash:
                print(f"[{self.port}] '{fname}' downloaded OK")
                # now make it available in our share list
                if fname not in self.shareFile:
                    self.shareFile.append(fname)
            else:
                print(f"[{self.port}] '{fname}' BAD HASH! expected {expected_hash}, got {actual_hash}")
                os.remove(dest)

        except Exception as e:
            print(f"[{self.port}] download_file error: {e}")


# ──────────────────────────── CLI ────────────────────────────
def main():
    # spin up 5 peers with their own shared folders
    peers = []
    for port, subdir in [(5000,"shared/p1"),
                         (6000,"shared/p2"),
                         (7000,"shared/p3"),
                         (8000,"shared/p4"),
                         (9000,"shared/p5")]:
        p = Peer("127.0.0.1", port, subdir)
        p.start()
        peers.append(p)
        time.sleep(0.1)

    # mesh them in a simple pattern
    peers[1].connect("127.0.0.1",5000); peers[0].connect("127.0.0.1",6000)
    peers[2].connect("127.0.0.1",5000); peers[0].connect("127.0.0.1",7000)
    peers[3].connect("127.0.0.1",6000); peers[1].connect("127.0.0.1",8000)
    peers[4].connect("127.0.0.1",6000); peers[1].connect("127.0.0.1",9000)

    active = peers[0]
    print("Type 'help' for commands.")

    while True:
        try:
            cmd = input(">>> ").strip().split()
            if not cmd:
                continue
            op = cmd[0].lower()

            if op == "help":
                print(
                    "Commands:\n"
                    "  peers       - show known peers\n"
                    "  showfiles   - show local shared files\n"
                    "  get <file>  - download a file\n"
                    "  exit        - quit"
                )

            elif op == "peers":
                print(active.known_peers)

            elif op == "showfiles":
                print(active.shareFile)

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