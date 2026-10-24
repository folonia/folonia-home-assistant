"""Le verrou vocal : code et mot de passe en empreinte, essais comptés, blocage et déblocage."""

from custom_components.folonia.voicelock import (
    VoiceLock,
    hash_code,
    normalize_lock_code,
    normalize_passphrase,
    passphrase_is_weak,
)


def test_code_en_chiffres_seulement() -> None:
    assert normalize_lock_code("24 68") == "2468"
    assert normalize_lock_code("1234-5678") == "12345678"
    assert normalize_lock_code("24.68") == "2468"
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


def test_mot_de_passe_normalise() -> None:
    assert normalize_passphrase("Dragon. Rouge !") == "dragon rouge"
    assert normalize_passphrase("  DRAGON   rouge ") == "dragon rouge"
    assert normalize_passphrase("Été à Noël") == "ete a noel"
    assert normalize_passphrase("Cœur d’œuf") == "coeur d oeuf"
    assert normalize_passphrase("Rémi 2") == "remi 2"
    # Au moins quatre lettres ou chiffres ; soixante-quatre caractères au plus.
    assert normalize_passphrase("chat") == "chat"
    assert normalize_passphrase("a b c") is None
    assert normalize_passphrase("...") is None
    assert normalize_passphrase("mot " * 16) == ("mot " * 16).strip()
    assert normalize_passphrase("mot " * 17) is None


def test_mot_de_passe_court_deconseille_pas_refuse() -> None:
    assert passphrase_is_weak("chat")
    assert not passphrase_is_weak("dragon")
    assert not passphrase_is_weak("le chat")


def test_code_ou_mot_de_passe_l_un_ou_l_autre_suffit() -> None:
    code_hash, code_salt = hash_code("2468")
    phrase_hash, phrase_salt = hash_code("dragon rouge")
    both = VoiceLock(code_hash, code_salt, phrase_hash, phrase_salt)
    assert both.configured and both.code_configured and both.phrase_configured
    assert both.check("24 68", now=0) == "ok"
    # Le mot de passe tel que le modèle peut le transcrire.
    assert both.check("Dragon. Rouge !", now=1) == "ok"
    assert both.check("dragon bleu", now=2) == "code_invalid"

    phrase_only = VoiceLock(None, None, phrase_hash, phrase_salt)
    assert phrase_only.configured and not phrase_only.code_configured
    assert phrase_only.check("2468", now=0) == "code_invalid"
    assert phrase_only.check("DRAGON ROUGE", now=1) == "ok"


def test_codes_et_mots_de_passe_faux_comptent_ensemble() -> None:
    code_hash, code_salt = hash_code("2468")
    phrase_hash, phrase_salt = hash_code("dragon rouge")
    lock = VoiceLock(code_hash, code_salt, phrase_hash, phrase_salt)
    for i, wrong in enumerate(("0000", "dragon bleu", "1111", "chat noir")):
        assert lock.check(wrong, now=i) == "code_invalid"
    assert lock.check("dragon vert", now=10) == "locked"
    assert lock.check("dragon rouge", now=11) == "locked"
    assert lock.check("2468", now=12) == "locked"


def test_empreinte_du_verrou_change_avec_un_secret() -> None:
    code_hash, code_salt = hash_code("2468")
    phrase_hash, phrase_salt = hash_code("dragon rouge")
    assert VoiceLock(code_hash, code_salt).fingerprint != (
        VoiceLock(code_hash, code_salt, phrase_hash, phrase_salt).fingerprint
    )
    assert (
        VoiceLock(code_hash, code_salt).fingerprint == VoiceLock(code_hash, code_salt).fingerprint
    )
