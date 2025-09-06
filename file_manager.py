import os
import threading
from typing import Dict, List

# Manages file operations for downloaded pieces
class FileManager:

    def __init__(self, torrent_file, download_dir: str = "downloads"):
        self.torrent = torrent_file
        self.download_dir = download_dir
        self.lock = threading.Lock()
        self.file_handles = {}  # path -> file handle
        
        # Create download directory structure
        self._create_directory_structure()

    # Create necessary directories for the torrent files
    def _create_directory_structure(self):
        print(f"Creating directory structure in: {self.download_dir}")
        
        # Create base download directory
        os.makedirs(self.download_dir, exist_ok=True)
        
        # Create directories for all files
        for file_info in self.torrent.files:
            file_path = os.path.join(self.download_dir, *file_info['path'])
            directory = os.path.dirname(file_path)
            
            if directory:
                os.makedirs(directory, exist_ok=True)
                print(f"Created directory: {directory}")

    # Write a completed piece to the appropriate file(s)
    def write_piece(self, piece_index: int, piece_data: bytes):
        with self.lock:
            print(f"Writing piece {piece_index} to disk ({len(piece_data)} bytes)")
            
            # Calculate piece offset in the torrent
            piece_offset = piece_index * self.torrent.piece_length
            
            # Find files that this piece overlaps with
            overlapping_files = self.torrent.get_files_for_piece(piece_index)
            
            # Write piece data to each overlapping file
            piece_pos = 0
            for file_info in overlapping_files:
                file_start = file_info['offset']
                file_end = file_start + file_info['length']
                
                # Calculate overlap between piece and file
                overlap_start = max(piece_offset, file_start)
                overlap_end = min(piece_offset + len(piece_data), file_end)
                
                if overlap_start < overlap_end:
                    # Calculate positions
                    file_write_pos = overlap_start - file_start
                    piece_read_pos = overlap_start - piece_offset
                    overlap_length = overlap_end - overlap_start
                    
                    # Extract data for this file
                    file_data = piece_data[piece_read_pos:piece_read_pos + overlap_length]
                    
                    # Write to file
                    self._write_to_file(file_info, file_write_pos, file_data)

    # Write data to a specific file at a specific position
    def _write_to_file(self, file_info: Dict, position: int, data: bytes):
        file_path = os.path.join(self.download_dir, *file_info['path'])
        
        try:
            # Open file if not already open
            if file_path not in self.file_handles:
                # Create file with correct size if it doesn't exist
                if not os.path.exists(file_path):
                    with open(file_path, 'wb') as f:
                        f.seek(file_info['length'] - 1)
                        f.write(b'\0')
                
                # Open file for random access
                self.file_handles[file_path] = open(file_path, 'r+b')
            
            # Write data at specified position
            file_handle = self.file_handles[file_path]
            file_handle.seek(position)
            file_handle.write(data)
            file_handle.flush()
            
            print(f"Wrote {len(data)} bytes to {file_path} at position {position}")
            
        except Exception as e:
            print(f"Error writing to file {file_path}: {e}")

    # Close all open file handles
    def close_all_files(self):
        with self.lock:
            for file_path, file_handle in self.file_handles.items():
                try:
                    file_handle.close()
                    print(f"Closed file: {file_path}")
                except Exception as e:
                    print(f"Error closing file {file_path}: {e}")
            
            self.file_handles.clear()

    # Verify that all files have the correct size
    def verify_file_integrity(self) -> bool:
        print("Verifying file integrity...")
        
        all_correct = True
        for file_info in self.torrent.files:
            file_path = os.path.join(self.download_dir, *file_info['path'])
            expected_size = file_info['length']
            
            try:
                actual_size = os.path.getsize(file_path)
                if actual_size != expected_size:
                    print(f"File size mismatch: {file_path}")
                    print(f"  Expected: {expected_size} bytes")
                    print(f"  Actual: {actual_size} bytes")
                    all_correct = False
                else:
                    print(f"File OK: {file_path} ({actual_size} bytes)")
            except FileNotFoundError:
                print(f"File not found: {file_path}")
                all_correct = False
            except Exception as e:
                print(f"Error checking file {file_path}: {e}")
                all_correct = False
        
        return all_correct

    # Get the full path to the download directory
    def get_download_path(self) -> str:
        return os.path.abspath(self.download_dir)

    # Clean up resources
    def cleanup(self):
        self.close_all_files()


