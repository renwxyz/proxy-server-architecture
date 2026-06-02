"""Skeleton web server manual berbasis socket untuk tugas arsitektur proxy."""

import os
import socket
import threading
from datetime import datetime


HOST = "0.0.0.0"
TCP_PORT = 8000
UDP_PORT = 9000
BUFFER_SIZE = 4096
MAX_REQUEST_SIZE = 8192
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".mp4": "video/mp4",
    ".ico": "image/x-icon",
}


STATUS_MESSAGES = {
    200: "OK",
    400: "Bad Request",
    403: "Forbidden",
    404: "Not Found",
    500: "Internal Server Error",
}


def main():
    """Entry point: inisialisasi socket, jalankan UDP thread, lalu TCP loop."""
    tcp_sock = None
    udp_sock = None

    try:
        tcp_sock = start_tcp_server()
        udp_sock = start_udp_server()

        udp_thread = threading.Thread(
            target=udp_echo_loop,
            args=(udp_sock,),
            name="udp-echo",
            daemon=True,
        )
        udp_thread.start()

        tcp_accept_loop(tcp_sock)
    except KeyboardInterrupt:
        print("\n[SERVER] Shutting down gracefully...")
    except OSError as error:
        print(f"[SERVER] Startup or socket error: {error}")
    finally:
        close_socket(tcp_sock)
        close_socket(udp_sock)
        print("[SERVER] Sockets closed. Goodbye.")


def start_tcp_server():
    """Membuat, bind, dan listen pada TCP socket."""
    tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    tcp_sock.bind((HOST, TCP_PORT))
    tcp_sock.listen()
    print(f"[TCP] Web server listening on {HOST}:{TCP_PORT}")
    return tcp_sock


def start_udp_server():
    """Membuat dan bind UDP echo socket."""
    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    udp_sock.bind((HOST, UDP_PORT))
    print(f"[UDP] Echo server listening on {HOST}:{UDP_PORT}")
    return udp_sock


def tcp_accept_loop(tcp_sock):
    """Menerima koneksi TCP dan meneruskan tiap koneksi ke worker thread."""
    while True:
        try:
            conn, addr = tcp_sock.accept()
        except OSError:
            break

        worker_name = f"tcp-worker-{addr[0]}:{addr[1]}"
        log_tcp_accept(addr, worker_name)
        worker = threading.Thread(
            target=handle_tcp_client,
            args=(conn, addr),
            name=worker_name,
            daemon=True,
        )
        worker.start()


def handle_tcp_client(conn, addr):
    """Menangani satu sesi TCP mulai dari baca request sampai kirim response."""
    method = "-"
    request_path = "-"
    http_version = "-"
    status_code = 500

    try:
        raw_data = read_http_request(conn)
        header_line = raw_data.split(b"\r\n", 1)[0]
        try:
            request_line = header_line.decode("ascii")
        except UnicodeDecodeError:
            request_line = ""

        request_parts = request_line.split()
        if len(request_parts) == 3:
            method, request_path, http_version = request_parts

        parsed_request = parse_http_request(raw_data)

        if parsed_request is None:
            response = serve_error(400)
            status_code = 400
        else:
            method = parsed_request["method"]
            request_path = parsed_request["path"]
            http_version = parsed_request["http_version"]
            response = serve_static_file(request_path)
            status_code = extract_status_code(response)

        send_response(conn, response)
    except Exception:
        response = serve_error(500)
        status_code = 500
        try:
            send_response(conn, response)
        except OSError:
            pass
    finally:
        log_request(addr, method, request_path, http_version, status_code)
        close_socket(conn)


def read_http_request(conn):
    """Membaca bytes dari koneksi sampai delimiter header HTTP ditemukan."""
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
    """Parse raw bytes HTTP request menjadi method, path, version, dan headers."""
    if not raw_data or b"\r\n\r\n" not in raw_data:
        return None

    header_bytes = raw_data.split(b"\r\n\r\n", 1)[0]

    try:
        header_text = header_bytes.decode("ascii")
    except UnicodeDecodeError:
        return None

    lines = header_text.split("\r\n")
    if not lines:
        return None

    request_line = lines[0]
    request_parts = request_line.split()
    if len(request_parts) != 3:
        return None

    method, path, http_version = request_parts
    if method != "GET" or not path.startswith("/"):
        return None

    if http_version not in ("HTTP/1.0", "HTTP/1.1"):
        return None

    headers = {}
    for line in lines[1:]:
        if not line:
            continue
        if ":" not in line:
            return None

        name, value = line.split(":", 1)
        name = name.strip()
        value = value.strip()
        if not name:
            return None

        headers[name] = value

    return {
        "method": method,
        "path": path,
        "http_version": http_version,
        "headers": headers,
    }


def resolve_file_path(request_path):
    """Memetakan URL path ke absolute filesystem path yang aman."""
    if request_path == "/":
        request_path = "/index.html"

    relative_path = request_path.lstrip("/")
    candidate_path = os.path.abspath(os.path.join(BASE_DIR, relative_path))

    try:
        if os.path.commonpath([BASE_DIR, candidate_path]) != BASE_DIR:
            return None
    except ValueError:
        return None

    if not os.path.isfile(candidate_path):
        return None

    return candidate_path


def get_mime_type(file_path):
    """Mengembalikan Content-Type berdasarkan ekstensi file."""
    _, extension = os.path.splitext(file_path)
    return MIME_TYPES.get(extension.lower(), "application/octet-stream")


def build_http_response(status_code, body_bytes, mime_type):
    """Membangun response HTTP/1.1 lengkap dalam bentuk bytes."""
    status_message = STATUS_MESSAGES.get(status_code, "Unknown")
    headers = [
        f"HTTP/1.1 {status_code} {status_message}",
        f"Content-Type: {mime_type}",
        f"Content-Length: {len(body_bytes)}",
        "Connection: close",
        "",
        "",
    ]
    header_bytes = "\r\n".join(headers).encode("ascii")
    return header_bytes + body_bytes


def send_response(conn, response_bytes):
    """Mengirim seluruh response bytes ke koneksi TCP."""
    conn.sendall(response_bytes)


def close_socket(sock):
    """Menutup socket dengan aman jika socket masih tersedia."""
    if sock is None:
        return

    try:
        sock.close()
    except OSError:
        pass


def serve_static_file(request_path):
    """Membaca static file yang diminta dan mengembalikan response HTTP lengkap."""
    file_path = resolve_file_path(request_path)
    if file_path is None:
        return serve_error(404)

    try:
        with open(file_path, "rb") as file:
            body_bytes = file.read()
    except OSError:
        return serve_error(500)

    mime_type = get_mime_type(file_path)
    return build_http_response(200, body_bytes, mime_type)


def serve_error(status_code):
    """Melayani halaman error HTML dari direktori status."""
    error_path = os.path.join(BASE_DIR, "status", f"{status_code}.html")

    try:
        with open(error_path, "rb") as file:
            body_bytes = file.read()
    except OSError:
        status_message = STATUS_MESSAGES.get(status_code, "Error")
        body_text = (
            "<!doctype html>"
            "<html>"
            "<head><title>{0} {1}</title></head>"
            "<body><h1>{0} {1}</h1></body>"
            "</html>"
        ).format(status_code, status_message)
        body_bytes = body_text.encode("utf-8")

    return build_http_response(status_code, body_bytes, "text/html; charset=utf-8")


def udp_echo_loop(udp_sock):
    """Menerima UDP datagram dan mengirim payload yang sama ke pengirim."""
    while True:
        try:
            data, client_addr = udp_sock.recvfrom(BUFFER_SIZE)
            udp_sock.sendto(data, client_addr)
            log_udp_echo(client_addr, len(data))
        except OSError as error:
            if udp_sock.fileno() == -1:
                break
            log_udp_error(error)


def log_request(client_addr, method, path, http_version, status_code):
    """Mencatat metadata request ke terminal."""
    client_ip = client_addr[0] if client_addr else "-"
    thread_name = threading.current_thread().name
    request_line = f"{method} {path} {http_version}"
    print(
        f'[{current_timestamp()}] [{status_code}] {client_ip} '
        f'"{request_line}" thread={thread_name}'
    )


def log_tcp_accept(client_addr, worker_name):
    """Mencatat koneksi TCP baru yang diterima accept loop."""
    client_ip, client_port = client_addr
    print(
        f"[{current_timestamp()}] [TCP] accepted {client_ip}:{client_port} "
        f"worker={worker_name}"
    )


def log_udp_echo(client_addr, byte_count):
    """Mencatat aktivitas UDP echo ke terminal."""
    client_ip, client_port = client_addr
    thread_name = threading.current_thread().name
    print(
        f"[{current_timestamp()}] [UDP] {client_ip}:{client_port} "
        f"echoed {byte_count} bytes thread={thread_name}"
    )


def log_udp_error(error):
    """Mencatat error UDP tanpa menghentikan server."""
    thread_name = threading.current_thread().name
    print(f"[{current_timestamp()}] [UDP] error={error} thread={thread_name}")


def current_timestamp():
    """Mengembalikan timestamp untuk format log server."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def extract_status_code(response_bytes):
    """Mengambil HTTP status code dari status line response."""
    try:
        status_line = response_bytes.split(b"\r\n", 1)[0]
        return int(status_line.split()[1])
    except (IndexError, ValueError):
        return 500


if __name__ == "__main__":
    main()
