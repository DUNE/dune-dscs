import socket
from concurrent.futures import ThreadPoolExecutor

HOSTS = [
    (2, "134.93.130.214"),
    (3, "134.93.131.35"),
    (6, "134.93.128.228"),
    (7, "134.93.128.229"),
    (9, "134.93.128.243"),
    (10, "134.93.129.24"),
    (11, "134.93.129.16"),
    (12, "134.93.131.161"),
    (13, "134.93.129.22"),
    (14, "134.93.129.26"),
]

PORTS = range(5555, 5655)


def check(target):
    weber, address, port = target
    try:
        with socket.create_connection((address, port), timeout=2):
            return weber, port, True
    except OSError:
        return weber, port, False


targets = [
    (weber, address, port)
    for weber, address in HOSTS
    for port in PORTS
]

results = {weber: [] for weber, _ in HOSTS}

print("Checking 1,000 emulator ports...", flush=True)

with ThreadPoolExecutor(max_workers=50) as pool:
    for weber, port, available in pool.map(check, targets):
        if not available:
            results[weber].append(port)

total = 0

for weber, address in HOSTS:
    missing = results[weber]
    working = 100 - len(missing)
    total += working
    print(f"Weber{weber:02d}: {working}/100 reachable")
    if missing:
        print("  Unavailable:", ", ".join(map(str, missing)))

print(f"\nTotal: {total}/1000 reachable")