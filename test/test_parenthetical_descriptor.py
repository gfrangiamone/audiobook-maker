"""Il descrittore di recupero deve preservare la scelta 'lettura testo tra
parentesi' attraverso un restart: senza, il recovery batch (optimize+auto-gen)
rigenererebbe l'audio col comportamento di default (rimozione), ignorando la
scelta dell'utente."""
import audiobook_app


def test_descriptor_carries_paren_flags_true():
    job = {"read_round_parens": True, "read_square_brackets": True}
    d = audiobook_app._build_job_descriptor(job, "generate")
    assert d["read_round_parens"] is True
    assert d["read_square_brackets"] is True


def test_descriptor_defaults_flags_false_when_absent():
    d = audiobook_app._build_job_descriptor({}, "generate")
    assert d["read_round_parens"] is False
    assert d["read_square_brackets"] is False


def test_descriptor_flags_independent():
    job = {"read_round_parens": True, "read_square_brackets": False}
    d = audiobook_app._build_job_descriptor(job, "optimize")
    assert d["read_round_parens"] is True
    assert d["read_square_brackets"] is False
