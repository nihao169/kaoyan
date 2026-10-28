from pathlib import Path
from typing import Protocol
from uuid import uuid4


class FileStore(Protocol):
    def put(self, body: bytes) -> str: ...
    def read(self, key: str) -> bytes: ...


class LocalFileStore:
    def __init__(self, root: Path):
        self.root = root

    def put(self, body: bytes) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        key = f'{uuid4()}.txt'
        (self.root / key).write_bytes(body)
        return key

    def read(self, key: str) -> bytes:
        if Path(key).name != key or '..' in key:
            raise ValueError('invalid file key')
        return (self.root / key).read_bytes()
