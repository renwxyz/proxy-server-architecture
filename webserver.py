import os
import socket
import threading
from datetime import datetime

HOST        = "0.0.0.0"   # dengarkan dari semua interface
TCP_PORT    = 8000
UDP_PORT    = 9000
BUFFER_SIZE = 4096
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css":  "text/css; charset=utf-8",
    ".js":   "application/javascript",
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".ico":  "image/x-icon",
}

def main():
    tcp_sock = start_tcp_server()
    udp_sock = start_udp_server()

    udp_thread = threading.Thread(target=udp_echo_loop, args=(udp_sock,), daemon=True)
    udp_thread.start()

    try:
        tcp_accept_loop(tcp_sock)
    except KeyboardInterrupt:
        print("\n[SERVER] Shutting down...")
    finally:
        tcp_sock.close()
        udp_sock.close()

def start_tcp_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((HOST, TCP_PORT))
    sock.listen()
    sock.settimeout(1.0)
    print(f"[TCP] Listening on {HOST}:{TCP_PORT}")
    return sock

def start_udp_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((HOST, UDP_PORT))
    print(f"[UDP] Listening on {HOST}:{UDP_PORT}")
    return sock

def tcp_accept_loop(tcp_sock):
    while True:
        try:
            conn, addr = tcp_sock.accept()
        except socket.timeout:
            continue
        worker = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
        worker.start()
        log_connection(addr, worker) 

def handle_client(conn, addr):
    method = path = "-"
    status = 500

    try:
        raw = read_request(conn)
        parsed = parse_request(raw)

        if parsed is None:
            status = 400
            conn.sendall(serve_error(400)[0])
        else:
            method = parsed["method"]
            path   = parsed["path"]
            response, status = serve_file(path)
            conn.sendall(response)

    except Exception:
        try:
            conn.sendall(serve_error(500)[0])
        except OSError:
            pass

    finally:
        log_request(addr, method, path, status)
        conn.close()

def read_request(conn):
    conn.settimeout(5)
    data = b""

    try:
        while b"\r\n\r\n" not in data:
            chunk = conn.recv(BUFFER_SIZE)
            if not chunk:
                break
            data += chunk
    except socket.timeout:
        pass

    return data

def parse_request(raw):
    if not raw or b"\r\n\r\n" not in raw:
        return None

    try:
        header_section = raw.split(b"\r\n\r\n", 1)[0].decode("ascii")
    except UnicodeDecodeError:
        return None

    lines = header_section.split("\r\n")
    parts = lines[0].split()

    if len(parts) != 3:
        return None

    method, path, version = parts

    if method != "GET":
        return None

    if version not in ("HTTP/1.0", "HTTP/1.1"):
        return None

    return {"method": method, "path": path, "version": version}

def resolve_path(request_path):
    if request_path == "/":
        request_path = "/index.html"

    full_path = os.path.abspath(os.path.join(BASE_DIR, request_path.lstrip("/")))

    if not full_path.startswith(BASE_DIR):
        return None

    if not os.path.isfile(full_path):
        return None

    return full_path

def build_response(status_code, body, mime_type):
    status_text = {
        200: "OK",
        400: "Bad Request",
        404: "Not Found",
        500: "Internal Server Error",
    }
    header = (
        f"HTTP/1.1 {status_code} {status_text.get(status_code, 'Error')}\r\n"
        f"Content-Type: {mime_type}\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Connection: close\r\n"
        f"\r\n"
    )
    return header.encode("ascii") + body

def serve_file(request_path):
    file_path = resolve_path(request_path)

    if file_path is None:
        return serve_error(404)

    try:
        with open(file_path, "rb") as f:
            body = f.read()
    except OSError:
        return serve_error(500)

    _, ext = os.path.splitext(file_path)
    mime_type = MIME_TYPES.get(ext.lower(), "application/octet-stream")

    return build_response(200, body, mime_type), 200

def serve_error(status_code):
    error_file = os.path.join(BASE_DIR, "status", f"{status_code}.html")

    try:
        with open(error_file, "rb") as f:
            body = f.read()
    except OSError:
        status_text = {400: "Bad Request", 404: "Not Found", 500: "Internal Server Error"}
        text = f"<h1>{status_code} {status_text.get(status_code, 'Error')}</h1>"
        body = text.encode("utf-8")

    return build_response(status_code, body, "text/html; charset=utf-8"), status_code

def udp_echo_loop(udp_sock):
    print("[UDP] Echo loop started")
    while True:
        try:
            data, client_addr = udp_sock.recvfrom(BUFFER_SIZE)
            udp_sock.sendto(data, client_addr)
            print(f"[UDP] {client_addr[0]}:{client_addr[1]} — echoed {len(data)} bytes")
        except OSError:
            break

def log_connection(addr, thread: threading.Thread):
    print(f"[{now()}] [TCP] Connection from {addr[0]}:{addr[1]} → Thread-{thread.ident}")


def log_request(addr, method, path, status):
    print(f'[{now()}] [{status}] {addr[0]} "{method} {path}"')


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

if __name__ == "__main__":
    main()
