import argparse

from piptools.scripts import compile, sync


def parse_args():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(
        title="Commands", required=True, metavar="COMMAND"
    )
    for mod in [compile, sync]:
        names = mod.__name__.split(".")
        subparser = subparsers.add_parser(
            names[-1], description=mod.cli.__doc__, help=mod.cli.__doc__
        )
        mod.add_args(subparser)
        subparser.set_defaults(func=mod.cli)
    return parser.parse_args()


# Enable ``python -m piptools ...``.
if __name__ == "__main__":
    args = parse_args()
    args.func(args)
