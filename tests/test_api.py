
import pytest
from unittest.mock import MagicMock, patch
import sys
import os

# Ensure we can import api
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import api
import config

@pytest.fixture
def client():
    api.app.config['TESTING'] = True
    with api.app.test_client() as client:
        yield client

@pytest.fixture
def mock_db():
    with patch('db_utils.DatabaseConnectionPool') as mock_pool:
        # Mock fetch_one to return something safe by default
        mock_pool.fetch_one.return_value = None
        yield mock_pool

def test_health_unprotected(client):
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json == {'message': 'Healthcheck OK!'}

def test_version_unauthorized(client):
    response = client.get('/version')
    assert response.status_code == 401

def test_version_authorized(client, mock_db):
    # Mock getting user by api key
    with patch('api.get_user_by_api_key') as mock_get_user:
        mock_get_user.return_value = (1, 'testuser')

        # Configure the mock app config version
        api.app.config['version'] = '0.0.0-test'

        response = client.get('/version', headers={'X-API-Key': 'valid-key'})
        assert response.status_code == 200
        assert response.json == {'version': '0.0.0-test'}

def test_nfc_transaction_missing_data(client, mock_db):
    with patch('api.get_user_by_api_key') as mock_get_user:
        mock_get_user.return_value = (1, 'testuser')
        response = client.put('/nfc-transaktion', headers={'X-API-Key': 'valid-key'}, json={})
        assert response.status_code == 400

