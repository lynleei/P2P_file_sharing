import socket
import threading
import time
import uuid
import os
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

                    msg_id    = msg_part[0]          # unique id
                    payload   = msg_part[1]          # free‑form text
                    msg_host  = msg_part[2]          # sender host
                    msg_port  = msg_part[3]          # sender port as string
                    msg_type  = msg_part[4]          # command type

                    print(f"Received: {payload}, {msg_type}")
                    
                    if msg_part[4] == "file_request":
                        if msg_part[1] in self.shareFile:
                             self.send_direct_message(msg_part[2], msg_part[3])
                             self.send_direct_message(msg_part[2], msg_part[3], msg_part[1])
                        else:
                             self.flood(message, exclude_conn=conn)
 
                    elif msg_part[4] == "file_response":
                         print(msg_part)
                         self.request.remove(msg_part[1])

                    # the ping/pong stuff
                    elif msg_type == "ping":
                        self.handle_ping(conn, msg_id, msg_host, msg_port)

                    elif msg_type == "pong":
                        self.handle_pong(payload)

                    # the download request stuff
                    elif msg_type == "download_request":
                        filename = msg_part[5] if len(msg_part) > 5 else ""
                        self.download_request(conn, (msg_host, msg_port), filename)

                    elif msg_type == "download_ready":
                        filename      = msg_part[5] if len(msg_part) > 5 else ""
                        expected_hash = msg_part[6] if len(msg_part) > 6 else None
                        self.receive_file(conn, filename, expected_hash)

                    elif msg_type == "list_request":
                        self._handle_list_request(conn)

                    elif msg_type == "list_response":
                        self._handle_list_response(payload)

 
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
        self.flood(msg)

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

    # new stuff added to run the main loop
    def list_files(self):
        msg_id = str(uuid.uuid4())
        msg = f"{msg_id};ASK_FOR_LIST;{self.host};{self.port};list_request"
        self.flood(msg)

    def _handle_list_request(self, conn):
        listing = "|".join(self.shareFile)      # simple: just filenames
        msg_id  = str(uuid.uuid4())
        resp = f"{msg_id};{listing};{self.host};{self.port};list_response"
        conn.sendall(resp.encode())

    def _handle_list_response(self, payload):
        for fname in payload.split("|"):
            if fname and fname not in self.shareFile:
                self.shareFile.append(fname)
        print("[INDEX] shareFile updated:", self.shareFile)

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
    """
    Minimal CLI so you can drive every major feature from the keyboard.

    Commands implemented
    --------------------
    help                     show this help
    ping                     discover peers (PING/PONG)
    peers                    print self.known_peers
    list                     broadcast list_request  ➜  TODO: you still need list_files() / list_response handler
    showfiles                print files we know about in self.shareFile
    say <msg>                flood a generic file_request with <msg>               (already works)
    get <filename>           start a download_request for <filename>               (request_file() OK)
    exit                     quit the program
    """
    # ---------- create two demo peers on localhost ----------
    peer1 = Peer("127.0.0.1", 5000)
    peer1.shareFile = ["file1.txt"]          # pretend we have one file to share
    peer1.start()                            # start listening in background

    time.sleep(1)                            # let peer1 finish binding

    peer2 = Peer("127.0.0.1", 6000)
    peer2.start()
    peer2.connect("127.0.0.1", 5000)         # peer2 → peer1

    peer1.connect("127.0.0.1", 6000)         # peer1 → peer2   (mesh them)

    # --------------- interactive loop ----------------
    active_peer = peer1                      # type commands that run on peer1
    print("[INFO] Type 'help' for commands.")
    while True:
        try:
            cmd = input(">>> ").strip().split()
            if not cmd:
                continue

            if cmd[0] == "help":
                print("""Commands
ping                 discover peers
peers                show known peers
list                 ask peers for file lists
showfiles            show local shareFile cache
get <filename>       download a file
say <msg>            broadcast a chat/file_request
exit                 quit
""")

            elif cmd[0] == "ping":
                active_peer.ping_peers()                     # ★ uses ping_peers()
                # NOTE: handle_ping / handle_pong must be called inside receive_connection()

            elif cmd[0] == "peers":
                print("Known peers:", active_peer.known_peers)

            elif cmd[0] == "list":
                # ★ TODO – you still need to add a list_files() method & its handlers
                if hasattr(active_peer, "list_files"):
                    active_peer.list_files()
                else:
                    print("list_files() not implemented yet!")

            elif cmd[0] == "showfiles":
                print("shareFile contents:", active_peer.shareFile)

            elif cmd[0] == "say" and len(cmd) >= 2:
                msg = " ".join(cmd[1:])
                active_peer.send_data(msg)                    # already works

            elif cmd[0] == "get" and len(cmd) == 2:
                filename = cmd[1]
                active_peer.request_file(filename)           # ★ kicks off download_request flow

            elif cmd[0] == "exit":
                print("[INFO] Bye!")
                break

            else:
                print("[WARN] Unknown command. Type 'help'.")

        except KeyboardInterrupt:
            print("\n[INFO] Ctrl‑C – exiting.")
            break



if __name__ == "__main__":
    main()