import os
import socket
import threading
import time
from datetime import datetime


PROXY_HOST       = "0.0.0.0"
PROXY_PORT       = 8080
SERVER_HOST      = "192.168.1.10"   # IP Laptop web server
SERVER_PORT      = 8000
BUFFER_SIZE      = 4096
MAX_REQUEST_SIZE = 8192
REQUEST_TIMEOUT  = 10               
BASE_DIR         = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR        = os.path.join(BASE_DIR, "cache")

STATUS_MESSAGES = {
    200: "OK",
    400: "Bad Request",
    502: "Bad Gateway",
    504: "Gateway Timeout",
}


def current_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def close_socket(sock):
    if sock is None:
        return
    try:
        sock.close()
    except OSError:
        pass


def log_request(addr, method, path, http_version, cache_status, elapsed_ms, status_code):
    client_ip    = addr[0] if addr else "-"
    request_line = f"{method} {path} {http_version}"
    cache_label  = "HIT " if cache_status == "HIT" else "MISS"
    print(
        f"[{current_timestamp()}] [{cache_label}] [{status_code}] {client_ip} "
        f'"{request_line}" {elapsed_ms:.1f}ms '
        f"thread={threading.current_thread().name}"
    )


def read_http_request(conn):
    raw_data = b""
    conn.settimeout(5)
    try:
        while b"\r\n\r\n" not in raw_data and len(raw_data) < MAX_REQUEST_SIZE:
            chunk = conn.recv(BUFFER_SIZE)
            if not chunk:
                break
            raw_data += chunk
    except socket.timeout:
        return raw_data
    return raw_data


def parse_http_request(raw_data):
    if not raw_data:
        return None

    try:
        text = raw_data.decode("utf-8", errors="replace")
        header_section = text.split("\r\n\r\n", 1)[0]
        lines = header_section.split("\r\n")

        parts = lines[0].split(" ", 2)
        if len(parts) < 3:
            return None

        method, path, http_version = parts[0], parts[1], parts[2]

        headers = {}
        for line in lines[1:]:
            if ":" in line:
                key, _, value = line.partition(":")
                headers[key.strip().lower()] = value.strip()

        return {
            "method":       method,
            "path":         path,
            "http_version": http_version,
            "headers":      headers,
        }
    except Exception:
        return None


def extract_status_code(response_bytes):
    try:
        status_line = response_bytes.split(b"\r\n", 1)[0].decode("utf-8", errors="replace")
        parts = status_line.split(" ", 2)
        return int(parts[1])
    except Exception:
        return 500


def get_cache_path(request_path):
    if request_path == "/":
        filename = "index.html"
    else:
        filename = request_path.lstrip("/").replace("/", "_")

    return os.path.join(CACHE_DIR, filename)


def is_cache_hit(cache_path):
    return os.path.isfile(cache_path)


def load_from_cache(cache_path):
    with open(cache_path, "rb") as f:
        return f.read()


def save_to_cache(cache_path, response_bytes, cache_lock):
    with cache_lock:
        tmp_path = cache_path + ".tmp"
        try:
            with open(tmp_path, "wb") as f:
                f.write(response_bytes)
            os.replace(tmp_path, cache_path)
        except OSError as e:
            print(f"[PROXY] Gagal menyimpan cache {cache_path}: {e}")
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def build_http_response(status_code, body_bytes, mime_type="text/html; charset=utf-8"):
    status_message = STATUS_MESSAGES.get(status_code, "Unknown")
    headers = (
        f"HTTP/1.1 {status_code} {status_message}\r\n"
        f"Content-Type: {mime_type}\r\n"
        f"Content-Length: {len(body_bytes)}\r\n"
        "Connection: close\r\n"
        "\r\n"
    )
    return headers.encode("utf-8") + body_bytes


def build_error_response(status_code):
    error_path = os.path.join(BASE_DIR, "status", f"{status_code}.html")
    try:
        with open(error_path, "rb") as f:
            body_bytes = f.read()
    except OSError:
        status_message = STATUS_MESSAGES.get(status_code, "Error")
        body_text = (
            f"<!doctype html><html>"
            f"<head><title>{status_code} {status_message}</title></head>"
            f"<body><h1>{status_code} {status_message}</h1></body>"
            f"</html>"
        )
        body_bytes = body_text.encode("utf-8")

    return build_http_response(status_code, body_bytes, "text/html; charset=utf-8")


def send_response(conn, response_bytes):
    try:
        conn.sendall(response_bytes)
    except OSError:
        pass 


def forward_to_server(request_path, original_headers):
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(REQUEST_TIMEOUT)
        sock.connect((SERVER_HOST, SERVER_PORT))

        request_line = f"GET {request_path} HTTP/1.1\r\n"
        headers = (
            f"Host: {SERVER_HOST}:{SERVER_PORT}\r\n"
            "Connection: close\r\n"
            "\r\n"
        )
        sock.sendall((request_line + headers).encode("ascii"))

        response = b""
        while True:
            chunk = sock.recv(BUFFER_SIZE)
            if not chunk:
                break
            response += chunk

        return response if response else None

    except (socket.timeout, ConnectionRefusedError, OSError):
        return None
    finally:
        close_socket(sock)


def handle_client(conn, addr, cache_lock):
    start_time = time.time()

    method       = "GET"
    path         = "/"
    http_version = "HTTP/1.1"
    cache_status = "MISS"
    status_code  = 400

    try:
        raw_data = read_http_request(conn)

        parsed = parse_http_request(raw_data)
        if parsed is None:
            response = build_error_response(400)
            send_response(conn, response)
            elapsed_ms = (time.time() - start_time) * 1000
            log_request(addr, method, path, http_version, cache_status, elapsed_ms, 400)
            return

        method       = parsed["method"]
        path         = parsed["path"]
        http_version = parsed["http_version"]
        headers      = parsed["headers"]

        cache_path = get_cache_path(path)

        if is_cache_hit(cache_path):
            cache_status = "HIT"
            response     = load_from_cache(cache_path)
            status_code  = extract_status_code(response)
            send_response(conn, response)
        else:
            cache_status = "MISS"
            response = forward_to_server(path, headers)

            if response is None:
                status_code = 504
                response    = build_error_response(504)
            else:
                status_code = extract_status_code(response)
                if status_code >= 500:
                    status_code = 502
                    response    = build_error_response(502)
                elif status_code == 200:
                    save_to_cache(cache_path, response, cache_lock)

            send_response(conn, response)

    except Exception as e:
        print(f"[PROXY] Error menangani client {addr}: {e}")
    finally:
        elapsed_ms = (time.time() - start_time) * 1000
        log_request(addr, method, path, http_version, cache_status, elapsed_ms, status_code)
        close_socket(conn)


def start_proxy_server():
    proxy_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    proxy_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    proxy_sock.bind((PROXY_HOST, PROXY_PORT))
    proxy_sock.listen(50)
    print(f"[PROXY] Proxy listening on {PROXY_HOST}:{PROXY_PORT}")
    print(f"[PROXY] Forwarding MISS requests to {SERVER_HOST}:{SERVER_PORT}")
    print(f"[PROXY] Cache directory: {CACHE_DIR}")
    return proxy_sock


def proxy_accept_loop(proxy_sock, cache_lock):
    while True:
        try:
            conn, addr = proxy_sock.accept()
        except OSError:
            break

        worker_name = f"proxy-worker-{addr[0]}:{addr[1]}"
        worker = threading.Thread(
            target=handle_client,
            args=(conn, addr, cache_lock),
            name=worker_name,
            daemon=True,
        )
        worker.start()


def main():
    proxy_sock = None
    cache_lock = threading.Lock()

    os.makedirs(CACHE_DIR, exist_ok=True)

    try:
        proxy_sock = start_proxy_server()
        proxy_accept_loop(proxy_sock, cache_lock)
    except KeyboardInterrupt:
        print("\n[PROXY] Shutting down gracefully...")
    except OSError as error:
        print(f"[PROXY] Startup error: {error}")
    finally:
        close_socket(proxy_sock)
        print("[PROXY] Socket closed. Goodbye.")


if __name__ == "__main__":
    main()
