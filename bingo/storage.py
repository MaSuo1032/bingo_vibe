"""投注紀錄與帳號密碼的檔案儲存（原子寫入 + 鎖，不依賴 Streamlit）。"""
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import threading
from typing import Dict, List

# 資料目錄可用環境變數指定 (例如掛載的持久化磁碟)；預設為目前工作目錄，與舊版相容
DATA_DIR = os.environ.get("BINGO_DATA_DIR", ".")


class StorageError(Exception):
    pass


class JsonStore:
    # 所有 Streamlit session 共用同一個 process，依檔案路徑共用一把鎖避免「讀取→修改→寫入」互相覆蓋
    _locks: Dict[str, threading.Lock] = {}
    _locks_guard = threading.Lock()

    def __init__(self, path: str):
        self.path = path
        with JsonStore._locks_guard:
            self.lock = JsonStore._locks.setdefault(os.path.abspath(path), threading.Lock())

    def _read(self) -> Dict:
        # 檔案不存在或為空 → 視為尚無資料；內容損毀則直接報錯，絕不回傳 {} 以免後續寫入洗掉所有資料
        if not os.path.exists(self.path) or os.path.getsize(self.path) == 0:
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            raise StorageError(f"資料檔 {self.path} 讀取失敗，為保護資料已停止寫入: {e}")
        if not isinstance(data, dict):
            raise StorageError(f"資料檔 {self.path} 格式錯誤，為保護資料已停止寫入。")
        return data

    def _write(self, data: Dict):
        # 先寫入暫存檔再原子替換，寫到一半中斷也不會留下損毀的檔案
        dir_name = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(dir_name, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, prefix=".bingo_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.path)
        except BaseException:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    def get(self, key: str, default=None):
        with self.lock:
            return self._read().get(key, default)

    def set(self, key: str, value):
        with self.lock:
            data = self._read()
            data[key] = value
            self._write(data)


class StorageManager:
    store = JsonStore(os.path.join(DATA_DIR, "bingo_bets_history.json"))

    @classmethod
    def load_bets(cls, username: str) -> List[Dict]:
        return cls.store.get(username, [])

    @classmethod
    def save_bets(cls, username: str, bets: List[Dict]):
        cls.store.set(username, bets)


class UserAuth:
    """暱稱密碼：PBKDF2-SHA256 雜湊後儲存，不保存明文。未設定密碼的暱稱維持舊版行為 (任何人可存取)。"""
    store = JsonStore(os.path.join(DATA_DIR, "bingo_users.json"))
    ITERATIONS = 200_000
    MIN_LENGTH = 4

    @classmethod
    def _hash(cls, password: str, salt: bytes) -> str:
        return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, cls.ITERATIONS).hex()

    @classmethod
    def has_password(cls, username: str) -> bool:
        return cls.store.get(username) is not None

    @classmethod
    def verify(cls, username: str, password: str) -> bool:
        record = cls.store.get(username)
        if record is None:
            return True
        if not password:
            return False
        return hmac.compare_digest(cls._hash(password, bytes.fromhex(record["salt"])), record["hash"])

    @classmethod
    def set_password(cls, username: str, password: str):
        if len(password) < cls.MIN_LENGTH:
            raise ValueError(f"密碼至少需要 {cls.MIN_LENGTH} 個字元。")
        with cls.store.lock:
            data = cls.store._read()
            if username in data:
                raise ValueError("此暱稱已設定密碼。")
            salt = secrets.token_bytes(16)
            data[username] = {"salt": salt.hex(), "hash": cls._hash(password, salt)}
            cls.store._write(data)
