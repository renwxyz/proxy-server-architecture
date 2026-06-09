"""
launcher.py — Jalankan 5 instance client.py secara bersamaan
Penggunaan:
    python launcher.py -mode tcp
    python launcher.py -mode udp
"""

import subprocess
import threading
import sys
import time

CLIENT_SCRIPT = "client.py"

TCP_PATHS = [
    "/index.html",
    "/css/style.css",
    "/index.html",
    "/index.html",
    "/css/style.css",
]

def run_client(client_id, args):
    print(f"[Client-{client_id}] START")
    start = time.time()

    proc = subprocess.run(
        [sys.executable, CLIENT_SCRIPT] + args,
        capture_output=True,
        text=True
    )

    elapsed = (time.time() - start) * 1000
    print(f"[Client-{client_id}] DONE {elapsed:.1f}ms")
    print(proc.stdout)

def main():
    if len(sys.argv) < 3 or sys.argv[1] != "-mode":
        print("Penggunaan: python launcher.py -mode tcp|udp")
        sys.exit(1)

    mode = sys.argv[2]

    if mode == "tcp":
        jobs = [["-mode", "tcp", path] for path in TCP_PATHS]
    elif mode == "udp":
        jobs = [["-mode", "udp"]] * 5
    else:
        print("mode harus tcp atau udp")
        sys.exit(1)

    threads = []
    for i, args in enumerate(jobs, start=1):
        t = threading.Thread(target=run_client, args=(i, args))
        threads.append(t)

    for t in threads:
        t.start()

    for t in threads:
        t.join()

    print("\nSemua client selesai.")

if __name__ == "__main__":
    main()
