import argparse
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="spool",
        description="Fast JSONL log explorer with TUI",
    )
    parser.add_argument("file", help="Path to .jsonl log file")
    args = parser.parse_args()

    from spool.tui.app import SpoolApp
    app = SpoolApp(args.file)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
