"""Le verrou vocal : code en empreinte, essais comptés, blocage et déblocage."""

from custom_components.folonia.voicelock import VoiceLock, hash_code, normalize_lock_code


def test_code_en_chiffres_seulement() -> None:
    assert normalize_lock_code("24 68") == "2468"
    assert normalize_lock_code("1234-5678") == "12345678"
    assert normalize_lock_code("123") is None
    assert normalize_lock_code("abcd") is None
    assert normalize_lock_code("123456789") is None


def test_empreinte_salee() -> None:
    first, salt = hash_code("2468")
    assert len(first) == 64 and len(salt) == 32
    assert hash_code("2468", salt) == (first, salt)
    assert hash_code("2468")[0] != first


def test_verrou_compte_les_codes_faux_sur_vingt_quatre_heures() -> None:
    lock_hash, salt = hash_code("2468")
    lock = VoiceLock(lock_hash, salt)
    assert lock.check(None, now=0) == "code_required"
    assert lock.check("0000", now=1) == "code_invalid"
    assert lock.check("2468", now=2) == "ok"
    assert list(lock.failures) == []
    for i in range(4):
        assert lock.check("0000", now=10 + i) == "code_invalid"
    assert lock.check("0000", now=20) == "locked"
    assert lock.check("2468", now=21) == "locked"
    # Vingt-quatre heures plus tard, les premiers échecs ne comptent plus.
    assert lock.check("2468", now=10 + 24 * 3600 + 1) == "ok"
    lock.reset()
    assert not lock.is_locked()


def test_sans_code_regle_rien_de_sensible() -> None:
    assert VoiceLock(None, None).check("2468") == "forbidden"
