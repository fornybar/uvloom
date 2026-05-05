import argparse
from pathlib import Path

from .plotting import plot_smiley


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot triangulated smiley face with meshpy")
    parser.add_argument("--output", default="smiley.png", help="Path for generated PNG")
    args = parser.parse_args()

    output = plot_smiley(Path(args.output))
    print(output)


if __name__ == "__main__":
    main()
