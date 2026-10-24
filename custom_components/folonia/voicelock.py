"""Le verrou vocal : un secret choisi ici, vérifié ici, jamais connu de Folonia.

Deux secrets possibles, l'un ou l'autre suffit : un code de quatre à huit chiffres, dit ou
tapé sur le clavier du téléphone, et un mot de passe parlé (un mot ou une courte phrase).
Oscar transmet ce que la personne a donné avec la demande ; il est comparé ici aux
empreintes, au code d'abord, puis au mot de passe. Cinq essais faux en vingt-quatre heures,
code et mot de passe ensemble, bloquent le verrou : plus rien de ce qui est sous code
jusqu'à ce que l'utilisateur rallume « Accès d'Oscar » ou enregistre un nouveau secret. Ce
module ne dépend pas de Home Assistant.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
import unicodedata
from collections import deque

from .const import LOCK_FAILURES, LOCK_WINDOW_SECONDS, PHRASE_ADVISED, PHRASE_MAX, PHRASE_MIN

_CODE = re.compile(r"^[0-9]{4,8}$")
_ITERATIONS = 50_000
#: Ce qu'un mot de passe peut devenir une fois normalisé : des mots de lettres et de chiffres.
_LIGATURES = str.maketrans({"œ": "oe", "æ": "ae", "Œ": "oe", "Æ": "ae"})


def normalize_lock_code(text: str) -> str | None:
    """Quatre à huit chiffres, espaces, points et tirets ignorés ; sinon `None`."""
    code = re.sub(r"[\s.-]", "", text)
    return code if _CODE.match(code) else None


def normalize_passphrase(text: str) -> str | None:
    """Le mot de passe tel qu'il est comparé ; `None` s'il ne peut pas en être un.

    Minuscules, accents et ponctuation retirés, espaces réduits : « Dragon. Rouge ! » et
    « dragon rouge » sont le même mot de passe, quelle que soit la transcription.
    Au moins quatre lettres ou chiffres, soixante-quatre caractères au plus.
    """
    decomposed = unicodedata.normalize("NFKD", text.translate(_LIGATURES))
    plain = "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()
    phrase = " ".join(re.sub(r"[^a-z0-9]+", " ", plain).split())
    letters = len(phrase.replace(" ", ""))
    if letters < PHRASE_MIN or len(phrase) > PHRASE_MAX:
        return None
    return phrase


def passphrase_is_weak(phrase: str) -> bool:
    """Moins de six lettres et un seul mot : accepté, mais déconseillé."""
    return len(phrase.replace(" ", "")) < PHRASE_ADVISED and " " not in phrase


def hash_code(code: str, salt: str | None = None) -> tuple[str, str]:
    """L'empreinte d'un secret (code ou mot de passe normalisé) et son sel, en hexadécimal."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", code.encode(), bytes.fromhex(salt), _ITERATIONS)
    return digest.hex(), salt


def _matches(secret: str | None, lock_hash: str | None, salt: str | None) -> bool:
    if not (secret and lock_hash and salt):
        return False
    expected, _ = hash_code(secret, salt)
    return hmac.compare_digest(expected, lock_hash)


class VoiceLock:
    """L'état du verrou : empreintes du code et du mot de passe, essais faux récents."""

    def __init__(
        self,
        lock_hash: str | None,
        salt: str | None,
        phrase_hash: str | None = None,
        phrase_salt: str | None = None,
    ) -> None:
        self._hash = lock_hash
        self._salt = salt
        self._phrase_hash = phrase_hash
        self._phrase_salt = phrase_salt
        self.failures: deque[float] = deque()

    @property
    def fingerprint(self) -> tuple[str | None, str | None, str | None, str | None]:
        """Ce qui distingue un verrou d'un autre : un secret changé le débloque."""
        return (self._hash, self._salt, self._phrase_hash, self._phrase_salt)

    @property
    def code_configured(self) -> bool:
        return bool(self._hash and self._salt)

    @property
    def phrase_configured(self) -> bool:
        return bool(self._phrase_hash and self._phrase_salt)

    @property
    def configured(self) -> bool:
        return self.code_configured or self.phrase_configured

    def _prune(self, now: float) -> None:
        while self.failures and now - self.failures[0] > LOCK_WINDOW_SECONDS:
            self.failures.popleft()

    def is_locked(self, now: float | None = None) -> bool:
        self._prune(now if now is not None else time.time())
        return len(self.failures) >= LOCK_FAILURES

    def check(self, code: str | None, now: float | None = None) -> str:
        """`ok`, `code_required`, `code_invalid`, `locked` ; `forbidden` sans secret réglé.

        `code` est ce que la personne a donné : un code chiffré, dit ou tapé, ou un mot de
        passe. Il est comparé au code, puis au mot de passe ; un essai faux compte une fois.
        """
        now = now if now is not None else time.time()
        if not self.configured:
            return "forbidden"
        if self.is_locked(now):
            return "locked"
        if not code:
            return "code_required"
        digits = normalize_lock_code(code)
        phrase = normalize_passphrase(code)
        if _matches(digits, self._hash, self._salt) or _matches(
            phrase, self._phrase_hash, self._phrase_salt
        ):
            self.failures.clear()
            return "ok"
        self.failures.append(now)
        return "locked" if len(self.failures) >= LOCK_FAILURES else "code_invalid"

    def reset(self) -> None:
        """Déblocage : « Accès d'Oscar » rallumé, ou nouveau secret enregistré."""
        self.failures.clear()
