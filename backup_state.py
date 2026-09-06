"""Consistent backup of the baseline SQLite log/cache, including committed WAL data."""
import argparse
import sqlite3
from contextlib import closing
from pathlib import Path


def backup(source: Path, destination: Path):
    if not source.is_file() or destination.exists() or source.resolve() == destination.resolve():
        raise ValueError("Use an existing source and a new, different destination")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as src:
        with closing(sqlite3.connect(destination)) as dst:
            src.backup(dst)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    backup(args.source, args.destination)
