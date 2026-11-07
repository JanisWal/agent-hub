"""Create the owner (first run) or an admin: python -m app.create_admin"""
import getpass
import sys

from . import users


def main() -> int:
    email = input("E-Mail: ")
    password = getpass.getpass("Passwort: ")
    if getpass.getpass("Passwort wiederholen: ") != password:
        print("Die Passwörter stimmen nicht überein.")
        return 1
    if users.password_problem(password):
        print("Mindestens 6 Zeichen mit Groß- und Kleinbuchstaben, einem Sonderzeichen und zwei Zahlen.")
        return 1
    role = "admin" if users.owner_exists() else "owner"  # the first account is the owner
    try:
        user = users.create_user(email, password, role=role)
    except ValueError as error:
        print(error)
        return 1
    print(f"{role.capitalize()} {user.email} angelegt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
