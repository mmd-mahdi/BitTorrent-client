import socket
import struct
import threading
import time
from typing import Optional, Callable, Set, List
from bitstring import BitArray
from utils import int_to_bytes, bytes_to_int

# BitTorrent protocol message types
MSG_CHOKE = 0
MSG_UNCHOKE = 1
MSG_INTERESTED = 2
MSG_NOT_INTERESTED = 3
MSG_HAVE = 4
MSG_BITFIELD = 5
MSG_REQUEST = 6
MSG_PIECE = 7
MSG_CANCEL = 8

# Represents a connection to a BitTorrent peer
class PeerConnection:

    # Initialize peer connection
    def __init__(self, ip: str, port: int, info_hash: bytes, peer_id: bytes):
        self.ip = ip
        self.port = port
        self.info_hash = info_hash
        self.peer_id = peer_id
        
        # Connection state
        self.socket = None
        self.connected = False
        self.handshake_completed = False
        self.last_message_time = 0
        self.keepalive_interval = 120  # 2 minutes
        self.request_timeout = 30  # 30 seconds timeout for piece requests
        
        # Peer state
        self.am_choking = True      # We are choking the peer
        self.am_interested = False  # We are interested in the peer
        self.peer_choking = True    # Peer is choking us
        self.peer_interested = False # Peer is interested in us
        
        # Piece availability
        self.peer_pieces = BitArray()  # Which pieces the peer has
        
        # Request management
        self.pending_requests = {}  # piece_index -> set of (begin, length)
        self.max_requests = 5       # Maximum concurrent requests
        
        # Callbacks
        self.on_piece_received = None  # Callback for received piece data
        self.on_have_received = None   # Callback for have messages
        
        # Threading
        self.receive_thread = None
        self.running = False

    # Connect to the peer
    def connect(self) -> bool:
        try:
            print(f"Connecting to peer {self.ip}:{self.port}")
            
            # Create socket and connect
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(10)  # 10 second timeout
            self.socket.connect((self.ip, self.port))
            
            self.connected = True
            
            # Perform BitTorrent handshake
            if self._perform_handshake():
                self.handshake_completed = True
                
                # Start receive thread
                self.running = True
                self.receive_thread = threading.Thread(target=self._receive_loop)
                self.receive_thread.daemon = True
                self.receive_thread.start()
                
                print(f"Successfully connected to peer {self.ip}:{self.port}")
                return True
            else:
                self.disconnect()
                return False
                
        except Exception as e:
            print(f"Failed to connect to peer {self.ip}:{self.port}: {e}")
            self.disconnect()
            return False

    # Perform BitTorrent protocol handshake
    def _perform_handshake(self) -> bool:
        try:
            # Send handshake: <pstrlen><pstr><reserved><info_hash><peer_id>
            pstr = b"BitTorrent protocol"
            pstrlen = len(pstr)
            reserved = b'\x00' * 8
            
            handshake = struct.pack('B', pstrlen) + pstr + reserved + self.info_hash + self.peer_id
            self.socket.send(handshake)
            
            # Receive handshake response
            response = self._receive_exact(68)  # Handshake is always 68 bytes
            if not response:
                return False
            
            # Parse handshake response
            resp_pstrlen = response[0]
            resp_pstr = response[1:1+resp_pstrlen]
            resp_reserved = response[1+resp_pstrlen:1+resp_pstrlen+8]
            resp_info_hash = response[1+resp_pstrlen+8:1+resp_pstrlen+8+20]
            resp_peer_id = response[1+resp_pstrlen+8+20:1+resp_pstrlen+8+20+20]
            
            # Verify handshake
            if resp_pstr != pstr or resp_info_hash != self.info_hash:
                print(f"Handshake verification failed with peer {self.ip}:{self.port}")
                return False
            
            print(f"Handshake completed with peer {self.ip}:{self.port}")
            return True
            
        except Exception as e:
            print(f"Handshake failed with peer {self.ip}:{self.port}: {e}")
            return False

    # Receive exactly the specified number of bytes
    def _receive_exact(self, length: int) -> Optional[bytes]:
        data = b''
        while len(data) < length:
            try:
                chunk = self.socket.recv(length - len(data))
                if not chunk:
                    return None
                data += chunk
            except Exception:
                return None
        return data

    # Main receive loop for handling peer messages
    def _send_keepalive(self):
        """Send a keep-alive message (length prefix with no message)"""
        if self.connected:
            try:
                # Keep-alive is just a length prefix of 0
                self.socket.send(int_to_bytes(0, 4))
            except Exception as e:
                print(f"Failed to send keep-alive to peer {self.ip}:{self.port}: {e}")
                self.disconnect()
                
    def _receive_loop(self):
        last_keepalive = time.time()
        
        while self.running and self.connected:
            try:
                # Send keep-alive if needed
                current_time = time.time()
                if current_time - last_keepalive > self.keepalive_interval:
                    self._send_keepalive()
                    last_keepalive = current_time
                
                # Receive message length (4 bytes)
                length_data = self._receive_exact(4)
                if not length_data:
                    break
                
                message_length = bytes_to_int(length_data)
                
                # Handle keep-alive message (length = 0)
                if message_length == 0:
                    continue
                
                # Receive message data
                message_data = self._receive_exact(message_length)
                if not message_data:
                    break
                
                # Process message
                self._handle_message(message_data)
                
            except Exception as e:
                print(f"Error in receive loop for peer {self.ip}:{self.port}: {e}")
                break
        
        self.disconnect()

    # Handle received peer message
    def _handle_message(self, message: bytes):
        # Update last message time for timeout tracking
        self.last_message_time = time.time()
        
        if len(message) == 0:
            # Keep-alive message received
            return
        
        message_type = message[0]
        payload = message[1:]
        
        if message_type == MSG_CHOKE:
            self.peer_choking = True
            print(f"Peer {self.ip}:{self.port} choked us")
            
        elif message_type == MSG_UNCHOKE:
            self.peer_choking = False
            print(f"Peer {self.ip}:{self.port} unchoked us")
            
        elif message_type == MSG_INTERESTED:
            self.peer_interested = True
            
        elif message_type == MSG_NOT_INTERESTED:
            self.peer_interested = False
            
        elif message_type == MSG_HAVE:
            if len(payload) >= 4:
                piece_index = bytes_to_int(payload[:4])
                self._handle_have(piece_index)
                
        elif message_type == MSG_BITFIELD:
            self._handle_bitfield(payload)
            
        elif message_type == MSG_REQUEST:
            # We don't handle upload requests in this simple client
            pass
            
        elif message_type == MSG_PIECE:
            if len(payload) >= 8:
                piece_index = bytes_to_int(payload[:4])
                begin = bytes_to_int(payload[4:8])
                block_data = payload[8:]
                self._handle_piece(piece_index, begin, block_data)
                
        elif message_type == MSG_CANCEL:
            # Handle cancel message if needed
            pass

    # Handle HAVE message
    def _handle_have(self, piece_index: int):
        if piece_index < len(self.peer_pieces):
            self.peer_pieces[piece_index] = True
            if self.on_have_received:
                self.on_have_received(piece_index)

    # Handle BITFIELD message
    def _handle_bitfield(self, bitfield_data: bytes):
        self.peer_pieces = BitArray(bytes=bitfield_data)
        print(f"Received bitfield from peer {self.ip}:{self.port}: {self.peer_pieces.count(True)} pieces")

    # Handle PIECE message
    def _handle_piece(self, piece_index: int, begin: int, block_data: bytes):
        # Remove from pending requests
        if piece_index in self.pending_requests:
            request_key = (begin, len(block_data))
            self.pending_requests[piece_index].discard(request_key)
            if not self.pending_requests[piece_index]:
                del self.pending_requests[piece_index]
        
        # Call callback with received piece data
        if self.on_piece_received:
            self.on_piece_received(piece_index, begin, block_data)

    # Send INTERESTED message
    def send_interested(self):
        if self.connected and not self.am_interested:
            self._send_message(MSG_INTERESTED, b'')
            self.am_interested = True
            print(f"Sent interested to peer {self.ip}:{self.port}")

    # Send NOT_INTERESTED message
    def send_not_interested(self):
        if self.connected and self.am_interested:
            self._send_message(MSG_NOT_INTERESTED, b'')
            self.am_interested = False

    # Request a piece block from the peer
    def request_piece(self, piece_index: int, begin: int, length: int):
        if not self.connected or self.peer_choking:
            return False

        current_time = time.time()
        
        # Check and remove timed out requests
        for p_index in list(self.pending_requests.keys()):
            for (b, l) in list(self.pending_requests[p_index]):
                if current_time - self.last_message_time > self.request_timeout:
                    self.pending_requests[p_index].remove((b, l))
                    print(f"Request timed out for piece {p_index} at offset {b}")
            if not self.pending_requests[p_index]:
                del self.pending_requests[p_index]
        
        # Check if we already have too many pending requests
        total_pending = sum(len(requests) for requests in self.pending_requests.values())
        if total_pending >= self.max_requests:
            return False
        
        # Check if peer has this piece
        if piece_index >= len(self.peer_pieces) or not self.peer_pieces[piece_index]:
            return False
        
        # Send request message
        payload = int_to_bytes(piece_index, 4) + int_to_bytes(begin, 4) + int_to_bytes(length, 4)
        self._send_message(MSG_REQUEST, payload)
        
        # Track pending request
        if piece_index not in self.pending_requests:
            self.pending_requests[piece_index] = set()
        self.pending_requests[piece_index].add((begin, length))
        
        return True

    # Send a message to the peer
    def _send_message(self, message_type: int, payload: bytes):
        if not self.connected:
            return
        
        try:
            message_length = 1 + len(payload)
            message = int_to_bytes(message_length, 4) + bytes([message_type]) + payload
            self.socket.send(message)
        except Exception as e:
            print(f"Failed to send message to peer {self.ip}:{self.port}: {e}")
            self.disconnect()

    # Check if peer has a specific piece
    def has_piece(self, piece_index: int) -> bool:
        return (piece_index < len(self.peer_pieces) and
                self.peer_pieces[piece_index])

    # Check if we can make requests to this peer
    def can_request(self) -> bool:
        return (self.connected and self.handshake_completed and
                not self.peer_choking and self.am_interested)

    # Disconnect from the peer
    def disconnect(self):
        self.running = False
        self.connected = False
        
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None
        
        print(f"Disconnected from peer {self.ip}:{self.port}")

