import pytest
from unittest.mock import Mock, patch
from torrent import TorrentFile
from piece_manager import PieceManager
from peer import PeerConnection
from file_manager import FileManager

def test_torrent_parser():
    # Test torrent file parsing
    torrent = TorrentFile("tests/test.torrent")
    assert len(torrent.piece_hashes) > 0
    assert torrent.piece_length > 0
    assert len(torrent.files) > 0

def test_piece_manager():
    # Test piece management and verification
    torrent = Mock()
    torrent.get_total_pieces.return_value = 10
    torrent.get_piece_length.return_value = 16384
    
    piece_manager = PieceManager(torrent)
    assert not piece_manager.is_complete()
    
    # Test piece completion
    piece_manager.add_piece_data(0, 0, b'test data')
    assert 0 not in piece_manager.completed_pieces

def test_peer_connection():
    # Test peer protocol
    peer = PeerConnection('127.0.0.1', 6881, b'infohash', b'peerid')
    assert not peer.connected
    assert not peer.handshake_completed

def test_file_manager():
    # Test file operations
    torrent = Mock()
    torrent.files = [{'path': ['test.txt'], 'length': 100, 'offset': 0}]
    
    file_manager = FileManager(torrent, 'test_downloads')
    assert file_manager.verify_file_integrity() == False  # File doesn't exist yet

if __name__ == '__main__':
    pytest.main([__file__])
