# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#   "rich>=13.9",
# ]
# ///

from rich.console import Console


def main() -> None:
    console = Console()
    console.print("Hello from a uv inline-dependency script!", style="bold green")


if __name__ == "__main__":
    main()
