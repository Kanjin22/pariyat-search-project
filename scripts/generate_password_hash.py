import sys
from werkzeug.security import generate_password_hash


def main():
    if len(sys.argv) != 2 or not sys.argv[1].strip():
        print('Usage: python scripts/generate_password_hash.py "<password>"')
        raise SystemExit(1)

    password = sys.argv[1]
    print(generate_password_hash(password))


if __name__ == '__main__':
    main()
