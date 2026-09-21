from pathlib import Path


def main() -> None:
    root = Path(__file__).parents[1] / "src" / "flow_control" / "rpc" / "generated"
    for path in sorted(root.rglob("*.py")):
        lines = path.read_text().splitlines()
        path.write_text(
            "\n".join(
                line for line in lines if not line.lstrip().startswith("#") and '"""' not in line
            )
            + "\n"
        )


if __name__ == "__main__":
    main()
