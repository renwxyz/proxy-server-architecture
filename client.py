import socket
import sys
import time

PROXY_IP = "[IP_ADDRESS_PROXY]"
PROXY_PORT = 8080

WEBSERVER_IP = "0.0.0.0"     
WEBSERVER_PORT = 9000

def run_tcp_client(resource_path):
    if not resource_path.startswith('/'):
        resource_path = '/' + resource_path

    print(f"Mengakses '{resource_path}' via Proxy ({PROXY_IP}:{PROXY_PORT})")
    
    tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp_socket.settimeout(5.0)
    try:
        tcp_socket.connect((PROXY_IP, PROXY_PORT))
        
        http_request = (
            f"GET {resource_path} HTTP/1.1\r\n"
            f"Host: {PROXY_IP}:{PROXY_PORT}\r\n"
            f"Accept: text/html,application/xhtml+xml,text/css;q=0.9\r\n"
            f"Connection: close\r\n\r\n"
        )
        tcp_socket.sendall(http_request.encode('utf-8'))
        
        response_bytes = b""
        while True:
            chunk = tcp_socket.recv(4096)
            if not chunk:
                break
            response_bytes += chunk
            
        try:
            header_part, body_part = response_bytes.split(b"\r\n\r\n", 1)
            
            print(f"\n[RAW HTTP RESPONSE HEADER]\n{header_part.decode('utf-8')}\n" + "="*60)
            
            if resource_path.endswith(('.html', '.css', '.js', '/')) or '.' not in resource_path.split('/')[-1]:
                print(f"\n[RESPONSE BODY (TEXT/HTML/CSS)]\n{body_part.decode('utf-8', errors='ignore')}")
            else:
                print(f"\n[RESPONSE BODY (BINARY DATA)]: Berhasil menerima {len(body_part)} bytes.")
            print("="*60 + "\n")
            
        except ValueError:
            print(f"\n[RAW RESPONSE (Malformed HTTP)]\n{response_bytes.decode('utf-8', errors='ignore')}")
            
    except socket.timeout:
        print("Error: koneksi ke server proxy gagal (504)")
    except ConnectionRefusedError:
        print("Error: Server proxy tidak berjalan.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        tcp_socket.close()

def run_udp_pinger():
    print(f"UDP mengirim paket QoS ke Web Server ({WEBSERVER_IP}:{WEBSERVER_PORT})")
    
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_socket.settimeout(1.0)
    
    try:
        rtt_list = []
        total_sent = 10
        total_payload_size = 0
        start_test_time = time.time()
        
        for seq in range(1, total_sent + 1):
            send_time = time.time()
            payload = f"Ping {seq} {send_time}"
            
            try:
                udp_socket.sendto(payload.encode('utf-8'), (WEBSERVER_IP, WEBSERVER_PORT))
                data, _ = udp_socket.recvfrom(1024)
                rtt = (time.time() - send_time) * 1000
                rtt_list.append(rtt)
                total_payload_size += len(data)
                
                print(f"Reply from {WEBSERVER_IP}: bytes={len(data)} seq={seq} RTT={rtt:.2f} ms")
            except socket.timeout:
                print(f"Request seq={seq} timed out.")
            except Exception as e:
                print(f"Error pada paket ke-{seq}: {e}")
                
            time.sleep(0.2)
            
        total_duration = time.time() - start_test_time
    finally:
        udp_socket.close()
        
    print("Uji QoS")
    packets_received = len(rtt_list)
    if packets_received == 0:
        print("Packet Loss: 100%")
        return

    packet_loss_pct = ((total_sent - packets_received) / total_sent) * 100
    differences = [j - i for i, j in zip(rtt_list, rtt_list[1:])]
    if differences:
        avg_diff = sum(differences) / len(differences)
        jitter = (sum((d - avg_diff) ** 2 for d in differences) / len(differences)) ** 0.5
    else:
        jitter = 0.0
    throughput_kbps = (total_payload_size * 8 / 1000) / total_duration if total_duration > 0 else 0
    
    print(f"Paket terkirim = {total_sent}, Diterima = {packets_received}, Hilang = {total_sent - packets_received}")
    print(f"Packet Loss   : {packet_loss_pct:.1f} %")
    print(f"RTT           : {min(rtt_list):.2f} ms / {sum(rtt_list)/packets_received:.2f} ms / {max(rtt_list):.2f} ms")
    print(f"Jitter        : {jitter:.2f} ms")
    print(f"Throughput    : {throughput_kbps:.2f} kbps\n")

if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] != "-mode":
        print("Cara akses client IFLAB")
        print("  Akses Halaman Utama : python client.py -mode tcp /index.html")
        print("  Akses Materi OSI    : python client.py -mode tcp /osi.html")
        print("  Akses File CSS      : python client.py -mode tcp /css/style.css")
        print("  Uji Parameter QoS   : python client.py -mode udp")
        sys.exit(1)
        
    mode = sys.argv[2].lower()
    
    if mode == "tcp":
        resource = sys.argv[3] if len(sys.argv) > 3 else "/index.html"
        run_tcp_client(resource)
    elif mode == "udp":
        run_udp_pinger()
    else:
        print("Error. Pilih 'tcp' atau 'udp'.")
        sys.exit(1)
