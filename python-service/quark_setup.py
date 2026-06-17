#!/usr/bin/env python3
"""Quark cloud storage QR login setup — runs on the server.

Usage:
    python quark_setup.py                     # saves to config/cookies.json
    python quark_setup.py /path/to/cookies.json
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from quark.qr_login import run_quark_setup

cookies_path = sys.argv[1] if len(sys.argv) > 1 else "config/cookies.json"
run_quark_setup(cookies_path)
