"""Le verrou vocal : un code choisi ici, vérifié ici, jamais connu de Folonia.

Le code est dit au téléphone, transmis par Oscar avec la commande, et comparé à son
empreinte. Cinq codes faux en vingt-quatre heures bloquent le verrou : plus aucune
commande sensible jusqu'à ce que l'utilisateur rallume « Accès d'Oscar » ou enregistre un
nouveau code. Ce module ne dépend pas de Home Assistant.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from collections import deque

from .const import LOCK_FAILURES, LOCK_WINDOW_SECONDS

_CODE = re.compile(r"^[0-9]{4,8}$")
_ITERATIONS = 50_000


def normalize_lock_code(text: str) -> str | None:
    """Quatre à huit chiffres, espaces et tirets ignorés ; sinon `None`."""
    code = re.sub(r"[\s-]", "", text)
    return code if _CODE.match(code) else None


def hash_code(code: str, salt: str | None = None) -> tuple[str, str]:
    """L'empreinte d'un code et son sel, en hexadécimal."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", code.encode(), bytes.fromhex(salt), _ITERATIONS)
    return digest.hex(), salt


class VoiceLock:
    """L'état du verrou : empreinte du code, codes faux récents."""

    def __init__(self, lock_hash: str | None, salt: str | None) -> None:
        self._hash = lock_hash
        self._salt = salt
        self.failures: deque[float] = deque()

    @property
    def configured(self) -> bool:
        return bool(self._hash and self._salt)

    def _prune(self, now: float) -> None:
        while self.failures and now - self.failures[0] > LOCK_WINDOW_SECONDS:
            self.failures.popleft()

    def is_locked(self, now: float | None = None) -> bool:
        self._prune(now if now is not None else time.time())
        return len(self.failures) >= LOCK_FAILURES

    def check(self, code: str | None, now: float | None = None) -> str:
        """`ok`, `code_required`, `code_invalid`, `locked` ; `forbidden` sans code réglé."""
        now = now if now is not None else time.time()
        if not self.configured:
            return "forbidden"
        if self.is_locked(now):
            return "locked"
        if not code:
            return "code_required"
        expected, _ = hash_code(code, self._salt)
        if hmac.compare_digest(expected, self._hash or ""):
            self.failures.clear()
            return "ok"
        self.failures.append(now)
        return "locked" if len(self.failures) >= LOCK_FAILURES else "code_invalid"

    def reset(self) -> None:
        """Déblocage : « Accès d'Oscar » rallumé, ou nouveau code enregistré."""
        self.failures.clear()
