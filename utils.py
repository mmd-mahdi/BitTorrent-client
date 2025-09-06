import hashlib
import struct
import socket
from typing import List, Tuple

# Calculate SHA1 hash of data
def sha1_hash(data: bytes) -> bytes:
    return hashlib.sha1(data).digest()

# Convert bytes to integer (big endian)
def bytes_to_int(data: bytes) -> int:
    return int.from_bytes(data, byteorder='big')

# Convert integer to bytes (big endian)
def int_to_bytes(value: int, length: int) -> bytes:
    return value.to_bytes(length, byteorder='big')

# Split data into chunks of specified size
def split_into_chunks(data: bytes, chunk_size: int) -> List[bytes]:
    return [data[i:i + chunk_size] for i in range(0, len(data), chunk_size)]

# Format bytes into human readable format
def format_bytes(bytes_count: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_count < 1024.0:
            return f"{bytes_count:.1f} {unit}"
        bytes_count /= 1024.0
    return f"{bytes_count:.1f} TB"

# Format download speed
def format_speed(bytes_per_second: float) -> str:
    return f"{format_bytes(int(bytes_per_second))}/s"

# Create a unique 20-byte peer ID
def create_peer_id() -> bytes:
    import random
    import string
    prefix = b"-PC0001-"  # Our client identifier
    suffix = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
    return prefix + suffix.encode('ascii')

# Parse compact peer format (6 bytes per peer: 4 for IP, 2 for port)
def parse_compact_peers(data: bytes) -> List[Tuple[str, int]]:
    peers = []
    for i in range(0, len(data), 6):
        if i + 6 <= len(data):
            ip_bytes = data[i:i+4]
            port_bytes = data[i+4:i+6]
            ip = socket.inet_ntoa(ip_bytes)
            port = struct.unpack('>H', port_bytes)[0]
            peers.append((ip, port))
    return peers

# Validate IP address and port
def validate_ip_port(ip: str, port: int) -> bool:
    try:
        socket.inet_aton(ip)
        return 1 <= port <= 65535
    except socket.error:
        return False
