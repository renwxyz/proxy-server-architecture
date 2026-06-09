import os
import socket
import threading
import time
from datetime import datetime
from urllib.parse import urlparse

PROXY_HOST  = "0.0.0.0"
PROXY_PORT  = 8080

SERVER_HOST = "127.0.0.1"   # ganti dengan IP laptop web server saat demo
SERVER_PORT = 8000

BUFFER_SIZE = 4096
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR   = os.path.join(BASE_DIR, "cache")

# Lock ini melindungi operasi tulis cache dari race condition
# saat banyak thread melayani request secara bersamaan
CACHE_LOCK  = threading.Lock()

def main():
    os.makedirs(CACHE_DIR, exist_ok=True)

    proxy_sock = start_proxy_server()

    try:
        proxy_accept_loop(proxy_sock)
    except KeyboardInterrupt:
        print("\n[PROXY] Shutting down...")
    finally:
        proxy_sock.close()


def start_proxy_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((PROXY_HOST, PROXY_PORT))
    sock.listen()
    sock.settimeout(1.0)
    print(f"[PROXY] Listening on {PROXY_HOST}:{PROXY_PORT}")
    print(f"[PROXY] Forwarding to {SERVER_HOST}:{SERVER_PORT}")
    return sock


def proxy_accept_loop(proxy_sock):
    while True:
        try:
            conn, addr = proxy_sock.accept()
        except socket.timeout:
            continue
        print(f"[{now()}] [PROXY] Connection from {addr[0]}:{addr[1]}")
        worker = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
        worker.start()

def handle_client(conn, addr):
    method = path = "-"
    status = 400
    cache_status = "MISS"
    start = time.time()

    try:
        raw = read_request(conn)
        parsed = parse_request(raw)

        if parsed is None:
            conn.sendall(build_error_response(400)[0])
            return

        method = parsed["method"]
        path   = parsed["path"]

        # Proxy ini hanya mendukung HTTP — tolak HTTPS tunneling
        if method == "CONNECT":
            conn.sendall(build_error_response(405)[0])
            status = 405
            return

        cache_path = get_cache_path(path)

        if is_cache_hit(cache_path):
            cache_status = "HIT"
            response, status = load_from_cache(cache_path)
        else:
            cache_status = "MISS"
            response, status = forward_to_server(path, parsed["headers"])

            # Hanya simpan ke cache jika response dari server sukses
            if status == 200:
                save_to_cache(cache_path, response)

        conn.sendall(response)

    except Exception:
        conn.sendall(build_error_response(500)[0])

    finally:
        elapsed = (time.time() - start) * 1000
        log_request(addr, method, path, cache_status, status, elapsed)
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

    # Browser yang dikonfigurasi via proxy mengirim absolute URL
    # contoh: GET http://192.168.1.10:8000/index.html HTTP/1.1
    # kita ekstrak path-nya saja
    if path.startswith("http"):
        path = urlparse(path).path or "/"

    headers = {}
    for line in lines[1:]:
        if ":" in line:
            key, _, value = line.partition(":")
            headers[key.strip().lower()] = value.strip()

    return {"method": method, "path": path, "version": version, "headers": headers}

def get_cache_path(request_path):
    # Ubah URL path menjadi nama file yang aman di filesystem
    if request_path == "/":
        filename = "index.html"
    else:
        filename = request_path.lstrip("/").replace("/", "_")
    return os.path.join(CACHE_DIR, filename)

def is_cache_hit(cache_path):
    return os.path.isfile(cache_path)

def load_from_cache(cache_path):
    with open(cache_path, "rb") as f:
        data = f.read()
    # Ekstrak status code dari response yang tersimpan
    status_line = data.split(b"\r\n", 1)[0].decode("ascii")
    status = int(status_line.split()[1])
    return data, status

def save_to_cache(cache_path, response_bytes):
    # Tulis ke file sementara dulu, baru rename — atomic write
    # supaya thread lain tidak membaca file yang setengah ditulis
    with CACHE_LOCK:
        tmp_path = cache_path + ".tmp"
        try:
            with open(tmp_path, "wb") as f:
                f.write(response_bytes)
            os.replace(tmp_path, cache_path)
        except OSError as e:
            print(f"[PROXY] Cache write failed: {e}")
            try:
                os.remove(tmp_path)
            except OSError:
                pass

def forward_to_server(path, headers):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((SERVER_HOST, SERVER_PORT))

        # Bangun request HTTP yang akan dikirim ke web server
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {SERVER_HOST}:{SERVER_PORT}\r\n"
            f"Connection: close\r\n"
        )
        # Teruskan header relevan dari browser ke server
        for key in ("user-agent", "accept", "accept-language"):
            if key in headers:
                request += f"{key}: {headers[key]}\r\n"
        request += "\r\n"

        sock.sendall(request.encode("ascii"))

        response = b""
        while True:
            chunk = sock.recv(BUFFER_SIZE)
            if not chunk:
                break
            response += chunk

        if not response:
            return build_error_response(502)

        status_line = response.split(b"\r\n", 1)[0].decode("ascii")
        status = int(status_line.split()[1])
        return response, status

    except socket.timeout:
        return build_error_response(504)
    except (ConnectionRefusedError, OSError):
        return build_error_response(502)
    finally:
        sock.close()

def build_error_response(status_code):
    status_text = {
        400: "Bad Request",
        405: "Method Not Allowed",
        500: "Internal Server Error",
        502: "Bad Gateway",
        504: "Gateway Timeout",
    }

    error_file = os.path.join(BASE_DIR, "status", f"{status_code}.html")
    try:
        with open(error_file, "rb") as f:
            body = f.read()
    except OSError:
        text = f"<h1>{status_code} {status_text.get(status_code, 'Error')}</h1>"
        body = text.encode("utf-8")

    header = (
        f"HTTP/1.1 {status_code} {status_text.get(status_code, 'Error')}\r\n"
        f"Content-Type: text/html; charset=utf-8\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Connection: close\r\n"
        f"\r\n"
    )
    return header.encode("ascii") + body, status_code

def log_request(addr, method, path, cache_status, status, elapsed_ms):
    label = "HIT " if cache_status == "HIT" else "MISS"
    print(f'[{now()}] [{label}] [{status}] {addr[0]} "{method} {path}" {elapsed_ms:.1f}ms')

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

if __name__ == "__main__":
    main()