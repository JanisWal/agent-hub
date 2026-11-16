"""Writes the mails as HTML files for a look in the browser (not a test).

    python tests/preview_mail.py OUT_DIR      (inside the web container, see PROJEKT.md, "Tests")

Makes mail-reset.html and mail-invite.html. Light and dark follow the browser (prefers-color-scheme), as in a mail
program that supports it. Uses a throwaway database, nothing is sent.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import db, mailtext, resets, users  # noqa: E402

out = sys.argv[1]
db.DB_PATH = os.path.join(tempfile.mkdtemp(), "preview.db")
user = users.create_user("janis@example.com", "Start1234")
users.set_profile(user.id, "Janis", "de")
user = users.get_by_id(user.id)
for kind, seconds in (("reset", resets.TOKEN_SECONDS), ("invite", resets.INVITE_SECONDS)):
    html = mailtext.build(kind, user, "https://hub.example.com/reset/AbCdEf123456_example-token", seconds)[2]
    with open(os.path.join(out, f"mail-{kind}.html"), "w", encoding="utf-8") as handle:
        handle.write(html)
print("written to", out)
