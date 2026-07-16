import json

from trainlab.main import create_app


def main() -> None:
    print(json.dumps(create_app().openapi(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
