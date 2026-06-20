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
    assert b"Login" in response.data or b"Anmelden" in response.data


def test_qr_code_requires_login(client_gui):
    response = client_gui.get("/qr_code?usercode=123&aktion=a")
    # Should redirect to login (root) because no session
    assert response.status_code == 302
    # Redirects to login page which is at root "/"
    assert response.headers["Location"].endswith("/")


def test_qr_code_with_login(client_gui):
    with client_gui.session_transaction() as sess:
        sess["user_id"] = 1

    # Mock erzeuge_qr_code to return a dummy image
    with patch("gui.erzeuge_qr_code") as mock_qr:
        mock_qr.return_value = Image.new("RGB", (10, 10))

        response = client_gui.get("/qr_code?usercode=123&aktion=a")
        assert response.status_code == 200
        assert response.mimetype == "image/png"


def test_handle_add_user_transaction_formatting():
    target_user = {
        "id": 42,
        "vorname": "Testolli",
        "email": "testolli@example.com"
    }
    form_data = {
        "beschreibung": "Test Buchung",
        "saldo_aenderung": "-1"
    }

    with (
        patch("gui.add_transaction") as mock_add_trans,
        patch("gui.get_user_notification_preference") as mock_pref,
        patch("gui.get_saldo_for_user") as mock_get_saldo,
        patch("gui._send_manual_transaction_email") as mock_send_email,
        patch("gui.flash") as mock_flash
    ):
        mock_add_trans.return_value = True
        mock_pref.return_value = True
        mock_get_saldo.return_value = 7

        success = gui._handle_add_user_transaction(form_data, target_user)

        assert success is True
        mock_send_email.assert_called_once()
        args, _ = mock_send_email.call_args
        # Arguments: target_user, beschreibung, saldo_aenderung_str, new_saldo, logo_pfad
        assert args[0] == target_user
        assert args[1] == "Test Buchung"
        # The crucial checks: should NOT contain the duplicate ' €' sign
        assert args[2] == "-1"
        assert args[3] == "7"

