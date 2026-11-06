"""Create an admin user: python -m app.create_admin"""
import getpass
import sys

from . import users


def main() -> int:
    email = input("E-Mail: ")
    password = getpass.getpass("Passwort: ")
    if getpass.getpass("Passwort wiederholen: ") != password:
        print("Die Passwörter stimmen nicht überein.")
        return 1
    try:
        user = users.create_user(email, password, is_admin=True)
    except ValueError as error:
        print(error)
        return 1
    print(f"Admin {user.email} angelegt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
