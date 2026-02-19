from unittest.mock import patch

import pytest
from PIL import Image

import gui


@pytest.fixture
def client_gui():
    gui.app.config["TESTING"] = True
    gui.app.config["SECRET_KEY"] = "testsecret"  # Ensure secret key for sessions
    with gui.app.test_client() as client:
        yield client


def test_login_page_loads(client_gui):
    response = client_gui.get("/")
    assert response.status_code == 200
    # Check if we are redirected to login or see login page elements
    # Since the root route is not defined in the outline I saw (it was truncated),
    # I assume there is a mechanic to redirect to login.
    # Looking at gui.py:
    # It has @app.route('/login', methods=['GET', 'POST']) but we didn't see the root route.
    # Let's try /login directly.
    response = client_gui.get("/login")
    # If login template exists it should render 200.
    # If we get 500/404 we know something is wrong.
    assert response.status_code in [200, 302]


def test_qr_code_requires_login(client_gui):
    response = client_gui.get("/qr_code?usercode=123&aktion=a")
    # Should redirect to login because no session
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_qr_code_with_login(client_gui):
    with client_gui.session_transaction() as sess:
        sess["user_id"] = 1

    # Mock erzeuge_qr_code to return a dummy image
    with patch("gui.erzeuge_qr_code") as mock_qr:

        mock_qr.return_value = Image.new("RGB", (10, 10))

        response = client_gui.get("/qr_code?usercode=123&aktion=a")
        assert response.status_code == 200
        assert response.mimetype == "image/png"
