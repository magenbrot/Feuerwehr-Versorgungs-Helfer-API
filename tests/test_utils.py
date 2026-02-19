
import pytest
import utils

def test_generate_api_key_string():
    key = utils.generate_api_key_string(32)
    assert isinstance(key, str)
    assert len(key) == 64  # secrets.token_hex(n) returns 2n hex chars

    key2 = utils.generate_api_key_string(16)
    assert len(key2) == 32

def test_hex_to_binary_valid():
    res = utils.hex_to_binary("deadbeef")
    assert res == b'\xde\xad\xbe\xef'

def test_hex_to_binary_invalid_hex():
    res = utils.hex_to_binary("zzzz")
    assert res is None

def test_hex_to_binary_invalid_type():
    res = utils.hex_to_binary(123)
    assert res is None
