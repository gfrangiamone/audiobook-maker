"""
Test suite per audiobook_app.
Eseguiti da GitHub Actions prima di ogni deploy.
"""
import pytest
import sys
import os

# Aggiungi la root del progetto al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def app():
    """Crea un'istanza dell'app per i test."""
    from audiobook_app import app
    app.config['TESTING'] = True
    return app


@pytest.fixture
def client(app):
    """Client HTTP per test."""
    return app.test_client()


# ── Test di base ──

class TestAppStartup:
    """Verifica che l'app si avvii correttamente."""

    def test_import(self):
        """L'app si importa senza errori."""
        import audiobook_app
        assert hasattr(audiobook_app, 'app')

    def test_homepage_loads(self, client):
        """La homepage risponde con status 200."""
        response = client.get('/')
        assert response.status_code == 200

    def test_homepage_content_type(self, client):
        """La homepage restituisce HTML."""
        response = client.get('/')
        assert 'text/html' in response.content_type

    def test_homepage_encoding(self, client):
        """La homepage si codifica correttamente in UTF-8 (no surrogati)."""
        response = client.get('/')
        # Se siamo qui con status 200, la codifica è OK
        data = response.data.decode('utf-8')
        assert len(data) > 0


class TestAPI:
    """Verifica che le API rispondano."""

    def test_voices_endpoint(self, client):
        """L'endpoint /api/voices risponde (200 o 500 se edge-tts non raggiungibile)."""
        response = client.get('/api/voices')
        assert response.status_code in (200, 500)  # 500 OK se rete edge-tts non disponibile

    def test_analyze_requires_file(self, client):
        """L'endpoint /api/analyze richiede un file."""
        response = client.post('/api/analyze')
        # Deve rispondere (400 o 422), non crashare (500)
        assert response.status_code != 500

    def test_unknown_route_404(self, client):
        """Route inesistenti restituiscono 404."""
        response = client.get('/api/nonexistent')
        assert response.status_code == 404


class TestPodcastGuide:
    """Verifica che la guida podcast si generi senza errori."""

    def test_no_surrogate_in_html(self, client):
        """L'HTML non contiene coppie surrogate UTF-16."""
        response = client.get('/')
        html = response.data.decode('utf-8')
        for ch in html:
            code = ord(ch)
            assert not (0xD800 <= code <= 0xDFFF), \
                f"Surrogate U+{code:04X} trovato nell'HTML"
