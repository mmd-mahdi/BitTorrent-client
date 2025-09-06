import requests
import socket
import struct
import random
import time
from typing import List, Tuple, Optional, Dict, Any
from urllib.parse import urlencode, urlparse
import bcoding
from utils import bytes_to_int, int_to_bytes, parse_compact_peers, create_peer_id

# Handles communication with BitTorrent trackers
class TrackerClient:
    # Initialize tracker client
    def __init__(self, torrent_file, peer_id: bytes = None):
        self.torrent = torrent_file
        self.peer_id = peer_id or create_peer_id()
        self.port = 6881  # Default BitTorrent port
        self.uploaded = 0
        self.downloaded = 0
        self.left = torrent_file.total_length

    # Announce to tracker and get peer list
    def announce(self, event: str = 'started') -> List[Tuple[str, int]]:
        print(f"Announcing to tracker with event: {event}")
        
        # Try primary tracker first
        peers = self._announce_to_tracker(self.torrent.announce, event)
        if peers:
            return peers
        
        # Try announce list if primary fails
        for tier in self.torrent.announce_list:
            for tracker_url in tier:
                try:
                    peers = self._announce_to_tracker(tracker_url, event)
                    if peers:
                        return peers
                except Exception as e:
                    print(f"Failed to announce to {tracker_url}: {e}")
                    continue
        
        return []

    # Announce to a specific tracker
    def _announce_to_tracker(self, tracker_url: str, event: str) -> List[Tuple[str, int]]:
        parsed_url = urlparse(tracker_url)
        
        if parsed_url.scheme == 'http' or parsed_url.scheme == 'https':
            return self._http_announce(tracker_url, event)
        elif parsed_url.scheme == 'udp':
            return self._udp_announce(tracker_url, event)
        else:
            raise Exception(f"Unsupported tracker protocol: {parsed_url.scheme}")

    # Announce to HTTP tracker
    def _http_announce(self, tracker_url: str, event: str) -> List[Tuple[str, int]]:
        print(f"HTTP announce to: {tracker_url}")
        
        # Prepare announce parameters
        params = {
            'info_hash': self.torrent.info_hash,
            'peer_id': self.peer_id,
            'port': self.port,
            'uploaded': self.uploaded,
            'downloaded': self.downloaded,
            'left': self.left,
            'compact': 1,  # Request compact peer format
            'event': event,
            'numwant': 50  # Request up to 50 peers
        }
        
        try:
            # Make HTTP request to tracker
            response = requests.get(tracker_url, params=params, timeout=10)
            response.raise_for_status()
            
            # Decode bencoded response
            tracker_response = bcoding.bdecode(response.content)
            
            # Check for tracker error
            if b'failure reason' in tracker_response:
                error = tracker_response[b'failure reason'].decode('utf-8')
                raise Exception(f"Tracker error: {error}")
            
            # Extract peer information
            peers_data = tracker_response.get(b'peers', b'')
            if isinstance(peers_data, bytes):
                # Compact format (6 bytes per peer)
                peers = parse_compact_peers(peers_data)
            else:
                # Dictionary format (list of peer dictionaries)
                peers = []
                for peer_dict in peers_data:
                    ip = peer_dict[b'ip'].decode('utf-8')
                    port = peer_dict[b'port']
                    peers.append((ip, port))
            
            # Extract additional tracker information
            interval = tracker_response.get(b'interval', 1800)  # Default 30 minutes
            seeders = tracker_response.get(b'complete', 0)
            leechers = tracker_response.get(b'incomplete', 0)
            
            print(f"Tracker response: {len(peers)} peers, {seeders} seeders, {leechers} leechers")
            print(f"Next announce in {interval} seconds")
            
            return peers
            
        except Exception as e:
            print(f"HTTP tracker announce failed: {e}")
            return []

    # Announce to UDP tracker
    def _udp_announce(self, tracker_url: str, event: str) -> List[Tuple[str, int]]:
        print(f"UDP announce to: {tracker_url}")
        
        parsed_url = urlparse(tracker_url)
        host = parsed_url.hostname
        port = parsed_url.port or 80
        
        try:
            # Create UDP socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(10)
            
            # Step 1: Connect request
            connection_id = self._udp_connect(sock, host, port)
            if not connection_id:
                return []
            
            # Step 2: Announce request
            peers = self._udp_announce_request(sock, host, port, connection_id, event)
            
            sock.close()
            return peers
            
        except Exception as e:
            print(f"UDP tracker announce failed: {e}")
            return []

    # UDP tracker connect handshake
    def _udp_connect(self, sock: socket.socket, host: str, port: int) -> Optional[int]:
        # Connect request format:
        # int64_t connection_id = 0x41727101980 (magic constant)
        # int32_t action = 0 (connect)
        # int32_t transaction_id = random
        
        transaction_id = random.randint(0, 2**32 - 1)
        connect_request = struct.pack('>QII', 0x41727101980, 0, transaction_id)
        
        try:
            sock.sendto(connect_request, (host, port))
            response, addr = sock.recvfrom(16)
            
            if len(response) < 16:
                return None
            
            # Parse connect response
            action, resp_transaction_id, connection_id = struct.unpack('>IIQ', response)
            
            if action != 0 or resp_transaction_id != transaction_id:
                return None
            
            return connection_id
            
        except Exception:
            return None

    # UDP tracker announce request
    def _udp_announce_request(self, sock: socket.socket, host: str, port: int, 
                            connection_id: int, event: str) -> List[Tuple[str, int]]:
        # Map event strings to numbers
        event_map = {'started': 2, 'completed': 1, 'stopped': 3}
        event_num = event_map.get(event, 0)
        
        transaction_id = random.randint(0, 2**32 - 1)
        
        # Announce request format (98 bytes total)
        announce_request = struct.pack(
            '>QII20s20sQQQIIIiH',
            connection_id,      # connection_id (8 bytes)
            1,                  # action = announce (4 bytes)
            transaction_id,     # transaction_id (4 bytes)
            self.torrent.info_hash,  # info_hash (20 bytes)
            self.peer_id,       # peer_id (20 bytes)
            self.downloaded,    # downloaded (8 bytes)
            self.left,          # left (8 bytes)
            self.uploaded,      # uploaded (8 bytes)
            event_num,          # event (4 bytes)
            0,                  # IP address (0 = default) (4 bytes)
            random.randint(0, 2**32 - 1),  # key (4 bytes)
            50,                 # num_want (4 bytes)
            self.port           # port (2 bytes)
        )
        
        try:
            sock.sendto(announce_request, (host, port))
            response, addr = sock.recvfrom(1024)
            
            if len(response) < 20:
                return []
            
            # Parse announce response
            action, resp_transaction_id, interval, leechers, seeders = struct.unpack('>IIIII', response[:20])
            
            if action != 1 or resp_transaction_id != transaction_id:
                return []
            
            # Parse peer list (6 bytes per peer)
            peers_data = response[20:]
            peers = parse_compact_peers(peers_data)
            
            print(f"UDP tracker response: {len(peers)} peers, {seeders} seeders, {leechers} leechers")
            
            return peers
            
        except Exception:
            return []

    # Update download/upload statistics
    def update_stats(self, downloaded: int, uploaded: int, left: int):
        self.downloaded = downloaded
        self.uploaded = uploaded
        self.left = left

