#!/usr/bin/env python3
"""
Test script to verify all imports work correctly after reorganization
"""

import sys
import os

# Add src directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

def test_core_imports():
    """Test core module imports"""
    try:
        from core import listener
        from core import multi_bot_launcher
        print("PASS: Core imports successful")
        return True
    except ImportError as e:
        print(f"FAIL: Core import failed: {e}")
        return False

def test_config_imports():
    """Test config module imports"""
    try:
        from config import multi_bot_config
        from config import channel_discovery
        from config import channel_mapper
        print("PASS: Config imports successful")
        return True
    except ImportError as e:
        print(f"FAIL: Config import failed: {e}")
        return False

def test_utils_imports():
    """Test utils module imports"""
    try:
        from utils import clickup_client_fetcher
        from utils import slack_channel_fetcher
        print("PASS: Utils imports successful")
        return True
    except ImportError as e:
        print(f"FAIL: Utils import failed: {e}")
        return False

def main():
    """Run all import tests"""
    print("Testing import structure after reorganization...")
    print("=" * 50)
    
    tests = [
        test_core_imports,
        test_config_imports,
        test_utils_imports
    ]
    
    results = []
    for test in tests:
        results.append(test())
    
    print("=" * 50)
    if all(results):
        print("SUCCESS: All imports working correctly!")
        return True
    else:
        print("ERROR: Some imports failed - check the errors above")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
