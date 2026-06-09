import socket
import sys
import time
import statistics

PROXY_HOST      = "127.0.0.1"  # ganti dengan IP laptop proxy saat demo
PROXY_PORT      = 8080

WEBSERVER_HOST  = "127.0.0.1"  # ganti dengan IP laptop web server saat demo
WEBSERVER_PORT  = 9000

BUFFER_SIZE     = 4096
UDP_PACKET_COUNT = 10
UDP_INTERVAL     = 0.2         # detik antar paket


def main():
    if len(sys.argv) < 3 or sys.argv[1] != "-mode":
        print("Penggunaan:")
        print("  python client.py -mode tcp /index.html")
        print("  python client.py -mode tcp /css/style.css")
        print("  python client.py -mode udp")
        sys.exit(1)

    mode = sys.argv[2].lower()

    if mode == "tcp":
        path = sys.argv[3] if len(sys.argv) > 3 else "/index.html"
        run_tcp(path)
    elif mode == "udp":
        run_udp()
    else:
        print("Error: mode harus 'tcp' atau 'udp'.")
        sys.exit(1)


def run_tcp(path):
    if not path.startswith("/"):
        path = "/" + path

    print(f"[TCP] Mengakses '{path}' via proxy {PROXY_HOST}:{PROXY_PORT}")

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)

    try:
        sock.connect((PROXY_HOST, PROXY_PORT))

        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {PROXY_HOST}:{PROXY_PORT}\r\n"
            f"Accept: text/html,text/css\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        )
        sock.sendall(request.encode("ascii"))

        response = b""
        while True:
            chunk = sock.recv(BUFFER_SIZE)
            if not chunk:
                break
            response += chunk

        # Pisahkan header dan body untuk ditampilkan
        if b"\r\n\r\n" in response:
            headers, body = response.split(b"\r\n\r\n", 1)
            print(f"\n[HEADER]\n{headers.decode('ascii')}")
            print("=" * 60)

            # Body teks ditampilkan langsung, binary cukup ukurannya
            if path.endswith((".html", ".css", ".js", "/")):
                print(f"[BODY]\n{body.decode('utf-8', errors='ignore')}")
            else:
                print(f"[BODY] Binary — {len(body)} bytes diterima")
        else:
            print(f"[RESPONSE] {response.decode('utf-8', errors='ignore')}")

    except socket.timeout:
        print("Error: koneksi timeout — proxy tidak merespons (504)")
    except ConnectionRefusedError:
        print("Error: proxy tidak berjalan")
    finally:
        sock.close()

def run_udp():
    print(f"[UDP] QoS test ke {WEBSERVER_HOST}:{WEBSERVER_PORT} — {UDP_PACKET_COUNT} paket")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(1.0)

    rtt_list = []
    sent = 0

    try:
        for seq in range(1, UDP_PACKET_COUNT + 1):
            payload = f"ping seq={seq} time={time.time()}"
            send_time = time.time()
            sent += 1

            try:
                sock.sendto(payload.encode("utf-8"), (WEBSERVER_HOST, WEBSERVER_PORT))
                data, _ = sock.recvfrom(BUFFER_SIZE)
                rtt = (time.time() - send_time) * 1000
                rtt_list.append(rtt)
                print(f"  Reply seq={seq} bytes={len(data)} RTT={rtt:.2f}ms")
            except socket.timeout:
                print(f"  Timeout seq={seq}")

            time.sleep(UDP_INTERVAL)

    finally:
        sock.close()

    print_stats(sent, rtt_list)

def print_stats(sent, rtt_list):
    received = len(rtt_list)
    lost = sent - received
    loss_pct = (lost / sent) * 100 if sent > 0 else 0

    print("\n--- Statistik QoS ---")
    print(f"Paket  : {sent} terkirim, {received} diterima, {lost} hilang")
    print(f"Loss   : {loss_pct:.1f}%")

    if received == 0:
        print("Tidak ada data RTT.")
        return

    min_rtt = min(rtt_list)
    avg_rtt = sum(rtt_list) / received
    max_rtt = max(rtt_list)

    # Jitter = σ(RTT_i - RTT_{i-1}) sesuai ketentuan soal
    if received > 1:
        diffs = [rtt_list[i+1] - rtt_list[i] for i in range(received - 1)]
        jitter = statistics.stdev(diffs)
    else:
        jitter = 0.0

    print(f"RTT    : min={min_rtt:.2f}ms  avg={avg_rtt:.2f}ms  max={max_rtt:.2f}ms")
    print(f"Jitter : {jitter:.2f}ms")
    print(f"Loss   : {loss_pct:.1f}%")

if __name__ == "__main__":
    main()

