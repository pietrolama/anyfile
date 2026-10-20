from __future__ import annotations

import sys

from anyfile import cli


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and (argv[0] in cli.COMMANDS or argv[0] in ("-h", "--help", "--version")):
        return cli.main(argv)
    from anyfile.app import run

    return run(argv)


if __name__ == "__main__":
    sys.exit(main())
