"""S13 (2026-10-13): i codici voucher completi finivano sul journal (creazione,
revoca, notifica, emissione per rimborso, ri-accredito, recovery): chi legge
i log li spende. Ora passano da payment.mask_code (prime 4 cifre e `…`).
Non fatto: legare il consumo del voucher all'email (serve il frontend)."""
import inspect
import re

import generation_engine
import payment
import routes_admin_vouchers


def test_mask_code_keeps_only_a_prefix():
    assert payment.mask_code("ABCD-EFGH-IJKL") == "ABCD…"
    assert payment.mask_code("AB") == "AB" and payment.mask_code("") == "" and payment.mask_code(None) == ""


def test_no_print_or_log_line_interpolates_a_full_voucher_code():
    for mod in (payment, routes_admin_vouchers, generation_engine):
        src = inspect.getsource(mod)
        bad = [l.strip() for l in src.splitlines()
               if re.search(r"(?i)(voucher|refund).*\{code\}", l) and "print(" in l]
        assert bad == [], (mod.__name__, bad)
    assert inspect.getsource(payment).count("mask_code(code)") >= 2
    assert inspect.getsource(routes_admin_vouchers).count("payment.mask_code(code)") == 3
