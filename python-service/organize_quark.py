"""CLI entry point for organizing Quark cloud storage."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
from quark.organize import run_organize

cookies_path = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "config/cookies.json"
dry_run = "--execute" not in sys.argv
run_organize(cookies_path, dry_run)
