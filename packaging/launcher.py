"""Entry point for frozen Linux distributions."""
import sys

if __name__ == "__main__":
    if sys.argv[1:] == ["--packaging-smoke-test"]:
        from smoke import run
        run()
    else:
        from rasterly.app import main
        raise SystemExit(main())
