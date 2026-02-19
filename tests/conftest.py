import pytest
import sys
import os

# Set TESTING env var before importing modules that have side effects
os.environ['TESTING'] = 'True'

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
