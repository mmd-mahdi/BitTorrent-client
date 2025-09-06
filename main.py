import sys
import time
import threading
import signal
from typing import List, Set
from torrent import TorrentFile
from tracker import TrackerClient
from peer import PeerConnection
from piece_manager import PieceManager
from file_manager import FileManager
from utils import format_bytes, format_speed, create_peer_id

# Main BitTorrent client class
class BitTorrentClient:

    # Initialize the BitTorrent client
    def __init__(self, torrent_path: str, download_dir: str = "downloads"):
        self.torrent_path = torrent_path
        self.download_dir = download_dir
        
        # Core components
        self.torrent = None
        self.tracker_client = None
        self.piece_manager = None
        self.file_manager = None
        
        # Peer management
        self.peers = {}  # (ip, port) -> PeerConnection
        self.peer_id = create_peer_id()
        self.max_peers = 30
        
        # State
        self.running = False
        self.start_time = None
        self.bytes_downloaded = 0
        self.download_speed = 0.0
        
        # Threading
        self.main_thread = None
        self.stats_thread = None
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    # Handle shutdown signals
    def _signal_handler(self, signum, frame):
        print("\nShutdown signal received. Cleaning up...")
        self.stop()

    # Start the BitTorrent client
    def start(self):
        try:
            print("Starting BitTorrent client...")
            print(f"Torrent file: {self.torrent_path}")
            print(f"Download directory: {self.download_dir}")
            print(f"Peer ID: {self.peer_id}")
            
            # Initialize components
            self._initialize_components()
            
            # Start main download loop
            self.running = True
            self.start_time = time.time()
            
            # Start statistics thread
            self.stats_thread = threading.Thread(target=self._stats_loop)
            self.stats_thread.daemon = True
            self.stats_thread.start()
            
            # Start main download thread
            self.main_thread = threading.Thread(target=self._download_loop)
            self.main_thread.daemon = True
            self.main_thread.start()
            
            # Wait for completion or interruption
            try:
                while self.running and not self.piece_manager.is_complete():
                    time.sleep(1)
                
                if self.piece_manager.is_complete():
                    print("\n🎉 Download completed successfully!")
                    self._verify_download()
                
            except KeyboardInterrupt:
                print("\nDownload interrupted by user")
            
        except Exception as e:
            print(f"Error starting client: {e}")
        finally:
            self.stop()

    # Initialize all client components
    def _initialize_components(self):
        print("Initializing components...")
        
        # Parse torrent file
        self.torrent = TorrentFile(self.torrent_path)
        
        # Initialize tracker client
        self.tracker_client = TrackerClient(self.torrent, self.peer_id)
        
        # Initialize piece manager with rate limiting
        self.piece_manager = PieceManager(self.torrent)
        self.piece_manager.on_piece_completed = self._on_piece_completed
        self.piece_manager.set_download_rate_limit(1024 * 1024)  # 1 MB/s default
        
        # Enable sequential download by default for better streaming
        self.piece_manager.set_sequential_download(True)
        
        # Initialize file manager
        self.file_manager = FileManager(self.torrent, self.download_dir)
        
        print("All components initialized successfully")

    # Main download loop
    def _download_loop(self):
        last_announce = 0
        announce_interval = 1800  # 30 minutes
        
        while self.running and not self.piece_manager.is_complete():
            try:
                # Announce to tracker periodically
                current_time = time.time()
                if current_time - last_announce > announce_interval:
                    self._announce_to_tracker()
                    last_announce = current_time
                
                # Connect to new peers if needed
                self._manage_peer_connections()
                
                # Request pieces from connected peers
                self._request_pieces_from_peers()
                
                # Clean up disconnected peers
                self._cleanup_disconnected_peers()
                
                time.sleep(1)  # Prevent busy waiting
                
            except Exception as e:
                print(f"Error in download loop: {e}")
                time.sleep(5)

    # Announce to tracker and get peer list
    def _announce_to_tracker(self):
        try:
            # Update tracker stats
            stats = self.piece_manager.get_download_stats()
            self.tracker_client.update_stats(
                downloaded=stats['bytes_downloaded'],
                uploaded=0,  # We don't upload in this simple client
                left=stats['total_bytes'] - stats['bytes_downloaded']
            )
            
            # Get peers from tracker
            event = 'started' if len(self.peers) == 0 else 'empty'
            peer_list = self.tracker_client.announce(event)
            
            print(f"Received {len(peer_list)} peers from tracker")
            
            # Add new peers
            for ip, port in peer_list:
                if (ip, port) not in self.peers and len(self.peers) < self.max_peers:
                    self._add_peer(ip, port)
            
        except Exception as e:
            print(f"Error announcing to tracker: {e}")

    # Add a new peer connection
    def _add_peer(self, ip: str, port: int):
        try:
            peer = PeerConnection(ip, port, self.torrent.info_hash, self.peer_id)
            peer.on_piece_received = self._on_piece_received
            peer.on_have_received = self._on_have_received
            
            self.peers[(ip, port)] = peer
            
            # Connect to peer in background
            threading.Thread(target=self._connect_peer, args=(peer,), daemon=True).start()
            
        except Exception as e:
            print(f"Error adding peer {ip}:{port}: {e}")

    # Connect to a peer (runs in background thread)
    def _connect_peer(self, peer: PeerConnection):
        if peer.connect():
            # Send interested message
            peer.send_interested()

    # Manage peer connections
    def _manage_peer_connections(self):
        connected_peers = sum(1 for peer in self.peers.values() if peer.connected)
        
        if connected_peers < 5 and len(self.peers) < self.max_peers:
            # Try to get more peers if we don't have enough connections
            threading.Thread(target=self._announce_to_tracker, daemon=True).start()

    # Request pieces from connected peers
    def _request_pieces_from_peers(self):
        for peer in self.peers.values():
            if peer.can_request():
                # Get available pieces from this peer
                available_pieces = set()
                for i in range(len(peer.peer_pieces)):
                    if peer.has_piece(i):
                        available_pieces.add(i)
                
                # Request next piece/block
                request = self.piece_manager.get_next_request(available_pieces)
                if request:
                    piece_index, offset, length = request
                    peer.request_piece(piece_index, offset, length)

    # Remove disconnected peers
    def _cleanup_disconnected_peers(self):
        disconnected = []
        for key, peer in self.peers.items():
            if not peer.connected:
                disconnected.append(key)
        
        for key in disconnected:
            del self.peers[key]

    # Handle received piece data
    def _on_piece_received(self, piece_index: int, offset: int, data: bytes):
        self.piece_manager.add_piece_data(piece_index, offset, data)
        self.bytes_downloaded += len(data)

    # Handle HAVE message from peer
    def _on_have_received(self, piece_index: int):
        """Handle HAVE message from peer"""
        pass  # Could be used for piece rarity tracking

    # Handle completed piece
    def _on_piece_completed(self, piece_index: int, piece_data: bytes):
        # Write piece to disk
        self.file_manager.write_piece(piece_index, piece_data)

    # Display download statistics
    def _stats_loop(self):
        last_bytes = 0
        last_time = time.time()

        while self.running:
            try:
                time.sleep(5)  # Update every 5 seconds

                current_time = time.time()
                current_bytes = self.bytes_downloaded

                # Calculate download speed
                time_diff = current_time - last_time
                bytes_diff = current_bytes - last_bytes

                if time_diff > 0:
                    self.download_speed = bytes_diff / time_diff

                # Get statistics
                stats = self.piece_manager.get_download_stats()
                connected_peers = sum(1 for peer in self.peers.values() if peer.connected)

                # Display progress
                print(f"\r Progress: {stats['completion_percentage']:.1f}% "
                      f"({stats['completed_pieces']}/{stats['total_pieces']} pieces) | "
                      f" Downloaded: {format_bytes(current_bytes)} / {format_bytes(stats['total_bytes'])} | "
                      f"⚡ Speed: {format_speed(self.download_speed)} | "
                      f" Peers: {connected_peers}", end="", flush=True)

                last_bytes = current_bytes
                last_time = current_time

            except Exception as e:
                print(f"\nError in stats loop: {e}")

    # Verify completed download
    def _verify_download(self):
        """Verify completed download"""
        print("Verifying download integrity...")

        if self.file_manager.verify_file_integrity():
            print("✅ All files verified successfully!")
            print(f"📁 Files saved to: {self.file_manager.get_download_path()}")
        else:
            print("❌ Some files failed verification")

    # Stop the BitTorrent client
    def stop(self):
        print("\nStopping BitTorrent client...")
        
        self.running = False
        
        # Disconnect all peers
        for peer in self.peers.values():
            peer.disconnect()
        
        # Clean up file manager
        if self.file_manager:
            self.file_manager.cleanup()
        
        # Final announce to tracker
        if self.tracker_client:
            try:
                self.tracker_client.announce('stopped')
            except:
                pass
        
        print("Client stopped")

def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py <torrent_file> [download_directory]")
        print("Example: python main.py example.torrent downloads")
        sys.exit(1)
    
    torrent_file = sys.argv[1]
    download_dir = sys.argv[2] if len(sys.argv) > 2 else "downloads"
    
    # Create and start client
    client = BitTorrentClient(torrent_file, download_dir)
    client.start()

if __name__ == "__main__":
    main()
