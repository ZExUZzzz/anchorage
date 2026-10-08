import sys


def main() -> int:
    from anchorage.app import run

    return run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
