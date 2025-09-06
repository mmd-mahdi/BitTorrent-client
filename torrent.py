import bcoding
import hashlib
from typing import Dict, List, Optional, Any, Union
from utils import sha1_hash, split_into_chunks

# Represents a parsed torrent file
class TorrentFile:
    # Initialize torrent from file path
    def __init__(self, torrent_path: str):
        self.torrent_path = torrent_path
        self.data = None
        self.info_hash = None
        self.piece_hashes = []
        self.files = []
        self.total_length = 0
        self.piece_length = 0
        self.name = ""
        self.announce = ""
        self.announce_list = []

        self._parse_torrent()

    # Helper to get dictionary value with either string or byte key
    def _get_key(self, data: Dict, key: str) -> Any:
        # Try byte key first, then string key
        byte_key = key.encode('utf-8')
        if byte_key in data:
            return data[byte_key]
        elif key in data:
            return data[key]
        else:
            raise KeyError(f"Key '{key}' not found in data")

    # Helper to decode string values that might be bytes or strings
    def _decode_string(self, value: Union[str, bytes]) -> str:
        if isinstance(value, bytes):
            return value.decode('utf-8')
        return value

    # Parse the torrent file and extract metadata
    def _parse_torrent(self):
        print(f"Parsing torrent file: {self.torrent_path}")

        try:
            with open(self.torrent_path, 'rb') as f:
                torrent_data = f.read()

            # Decode bencoded torrent data
            self.data = bcoding.bdecode(torrent_data)

            print(f"Torrent data keys: {list(self.data.keys())}")

            info = self._get_key(self.data, 'info')
            print(f"Info keys: {list(info.keys())}")

            # Calculate info hash (SHA1 of bencoded info dictionary)
            if b'info' in self.data:
                info_bencoded = bcoding.bencode(self.data[b'info'])
            else:
                info_bencoded = bcoding.bencode(self.data['info'])
            self.info_hash = sha1_hash(info_bencoded)

            # Extract basic torrent information
            self.name = self._decode_string(self._get_key(info, 'name'))
            self.piece_length = self._get_key(info, 'piece length')

            # Extract piece hashes (20 bytes each)
            pieces_data = self._get_key(info, 'pieces')
            if isinstance(pieces_data, str):
                pieces_data = pieces_data.encode('latin-1')  # Preserve binary data
            self.piece_hashes = split_into_chunks(pieces_data, 20)

            # Extract tracker information
            self.announce = self._decode_string(self._get_key(self.data, 'announce'))

            try:
                announce_list_data = self._get_key(self.data, 'announce-list')
                self.announce_list = [
                    [self._decode_string(url) for url in tier]
                    for tier in announce_list_data
                ]
            except KeyError:
                self.announce_list = []

            # Parse file structure (single-file vs multi-file)
            try:
                files_data = self._get_key(info, 'files')
                # Multi-file torrent
                self._parse_multi_file(info)
            except KeyError:
                # Single-file torrent
                self._parse_single_file(info)

            print(f"Torrent parsed successfully:")
            print(f"  Name: {self.name}")
            print(f"  Total size: {self.total_length} bytes")
            print(f"  Piece length: {self.piece_length} bytes")
            print(f"  Number of pieces: {len(self.piece_hashes)}")
            print(f"  Number of files: {len(self.files)}")
            print(f"  Tracker: {self.announce}")

        except Exception as e:
            print(f"Error details: {type(e).__name__}: {e}")
            if hasattr(self, 'data') and self.data:
                print(f"Available keys in torrent: {list(self.data.keys())}")
            raise Exception(f"Failed to parse torrent file: {e}")

    # Parse single-file torrent structure
    def _parse_single_file(self, info: Dict):
        file_length = self._get_key(info, 'length')
        self.total_length = file_length

        # Single file entry
        self.files = [{
            'path': [self.name],
            'length': file_length,
            'offset': 0
        }]

    # Parse multi-file torrent structure
    def _parse_multi_file(self, info: Dict):
        files_info = self._get_key(info, 'files')
        offset = 0

        for file_info in files_info:
            file_length = self._get_key(file_info, 'length')
            file_path_data = self._get_key(file_info, 'path')
            file_path = [self._decode_string(part) for part in file_path_data]
            
            self.files.append({
                'path': [self.name] + file_path,
                'length': file_length,
                'offset': offset
            })
            
            offset += file_length
        
        self.total_length = offset

    # Get SHA1 hash for a specific piece
    def get_piece_hash(self, piece_index: int) -> bytes:
        if 0 <= piece_index < len(self.piece_hashes):
            return self.piece_hashes[piece_index]
        raise IndexError(f"Piece index {piece_index} out of range")

    # Get length of a specific piece (last piece might be shorter)
    def get_piece_length(self, piece_index: int) -> int:
        if piece_index == len(self.piece_hashes) - 1:
            # Last piece might be shorter
            return self.total_length - (piece_index * self.piece_length)
        return self.piece_length

    # Get total number of pieces
    def get_total_pieces(self) -> int:
        return len(self.piece_hashes)

    # Get list of files that overlap with a specific piece
    def get_files_for_piece(self, piece_index: int) -> List[Dict]:
        piece_start = piece_index * self.piece_length
        piece_end = piece_start + self.get_piece_length(piece_index)
        
        overlapping_files = []
        for file_info in self.files:
            file_start = file_info['offset']
            file_end = file_start + file_info['length']
            
            # Check if piece and file overlap
            if piece_start < file_end and piece_end > file_start:
                overlapping_files.append(file_info)
        
        return overlapping_files

