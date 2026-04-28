"""
Versione dell'applicazione Audiobook Maker.
Aggiornare __version__ ad ogni rilascio.
"""
from datetime import datetime

__version__ = "3.8.11"

# Data dell'ultimo aggiornamento (AAAA-MM) - si aggiorna automaticamente
__updated_date__ = datetime.now().strftime("%Y-%m")

# Mese/anno formattato per il template (es. "March 2026")
def get_formatted_date():
    """Restituisce la data formattata per l'ultimo aggiornamento."""
    dt = datetime.now()
    month_names = {
        1: "January", 2: "February", 3: "March", 4: "April",
        5: "May", 6: "June", 7: "July", 8: "August",
        9: "September", 10: "October", 11: "November", 12: "December"
    }
    return f"{month_names[dt.month]} {dt.year}"
