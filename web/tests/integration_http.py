"""End-to-end check of a running Agent-Hub over HTTP (standard library only).

    python integration_http.py BASE_URL EMAIL PASSWORD [EMAIL2 PASSWORD2]

Logs in, walks through projects, board and settings, and removes what it created. With a second
(normal) account it also checks that this account sees and changes nothing of the first one.
Run it against a test instance (see PROJEKT.md, "Tests"). Against the live site only with test
accounts. Exit code 0 = all fine.
"""
import http.cookiejar
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

base, email, password = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3]
failures = []


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(NoRedirect, urllib.request.HTTPCookieProcessor(jar))


def call(method, path, data=None, as_json=False, cookies=True, who=None):
    """Returns (status, headers, body). Redirects are not followed. `who` is another client
    (its own cookies) for the checks with a second account."""
    body, headers = None, {}
    if data is not None:
        body = json.dumps(data).encode() if as_json else urllib.parse.urlencode(data).encode()
        headers["Content-Type"] = "application/json" if as_json else "application/x-www-form-urlencoded"
    request = urllib.request.Request(base + path, body, headers, method=method)
    client = who or (opener if cookies else urllib.request.build_opener(NoRedirect))
    try:
        with client.open(request, timeout=15) as response:
            return response.status, response.headers, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read().decode()


def check(name, condition, detail=""):
    print(("ok   " if condition else "FAIL ") + name + ("" if condition else f"  {detail}"))
    if not condition:
        failures.append(name)


# --- without login -------------------------------------------------------------------------
status, headers, body = call("GET", "/login")
check("login page", status == 200 and 'name="password"' in body)
check("security headers", headers.get("X-Content-Type-Options") == "nosniff"
      and headers.get("X-Frame-Options") == "SAMEORIGIN" and headers.get("Cache-Control") == "no-store")
for path in ("/docs", "/redoc", "/openapi.json"):
    check(f"{path} is off", call("GET", path)[0] == 404, path)
check("health", call("GET", "/health")[0] == 200)
# password reset: same answer for any address, bad links are refused (no mail is sent here)
check("login links to forgot page", 'href="/forgot"' in call("GET", "/login")[2])
status, _, body = call("GET", "/forgot")
check("forgot page", status == 200 and 'name="email"' in body)
status, _, known = call("POST", "/forgot", {"email": email}, cookies=False)
status2, _, unknown = call("POST", "/forgot", {"email": "nobody-here@example.invalid"}, cookies=False)
check("forgot answers the same for known and unknown address", status == status2 == 200 and known == unknown)
check("forgot needs an address", call("POST", "/forgot", {"email": "x"}, cookies=False)[0] == 400)
check("bad reset link page", call("GET", "/reset/not-a-token", cookies=False)[0] == 400)
check("bad reset link post", call("POST", "/reset/not-a-token", {"new": "Aa1!bb2", "repeat": "Aa1!bb2"}, cookies=False)[0] == 400)
status, headers, _ = call("GET", "/", cookies=False)
check("home needs login", status == 303 and headers["Location"] == "/login")
check("api needs login", call("POST", "/projects/move", {"id": 1, "page": 1, "index": 0}, True, cookies=False)[0] == 401)
check("static served", call("GET", "/static/core.js")[0] == 200 and call("GET", "/static/app.css")[0] == 200)
check("wrong password", call("POST", "/login", {"email": email, "password": password + "x"})[0] == 401)

# --- login ---------------------------------------------------------------------------------
status, headers, _ = call("POST", "/login", {"email": email, "password": password})
check("login", status == 303 and headers["Location"] == "/")
check("cookie flags", "HttpOnly" in "".join(headers.get_all("Set-Cookie") or []))
status, _, body = call("GET", "/")
check("dashboard", status == 200 and 'id="pages"' in body)
for name in re.findall(r'/static/([\w.]+)"', body):
    check(f"asset {name}", call("GET", "/static/" + name)[0] == 200)

# --- projects ------------------------------------------------------------------------------
status, headers, _ = call("POST", "/projects", {"name": "Integration <test>"})
check("create project", status == 303)
_, _, body = call("GET", "/")
match = re.search(r'data-id="(\d+)"[^>]*>(?:(?!</).)*?Integration', body, re.S) or re.search(
    r'href="/projects/(\d+)"', body)
project = match.group(1) if match else None
check("project listed and escaped", project is not None and "Integration &lt;test&gt;" in body)
if project:
    status, _, body = call("GET", f"/projects/{project}")
    check("project page", status == 200 and 'class="board"' in body)
    check("unknown project 404", call("GET", "/projects/999999")[0] == 404)

    # --- board ---
    check("create item", call("POST", f"/projects/{project}/items", {"kind": "bug", "title": "First"})[0] == 303)
    check("create second", call("POST", f"/projects/{project}/items", {"kind": "bug", "title": "Second"})[0] == 303)
    _, _, body = call("GET", f"/projects/{project}")
    ids = re.findall(r'class="card[^"]*"[^>]*data-id="(\d+)"', body) or re.findall(r'data-id="(\d+)"', body)[-2:]
    check("items listed", len(ids) >= 2, str(ids))
    if len(ids) >= 2:
        first, second = ids[-2], ids[-1]
        check("rename", call("POST", f"/items/{first}", {"title": "Renamed"})[0] == 303)
        check("reorder", call("POST", "/items/reorder", {"kind": "bug", "ids": [int(second), int(first)]}, True)[0] == 200)
        check("bad reorder", call("POST", "/items/reorder", {"kind": "bug"}, True)[0] == 400)
        check("discard", call("POST", f"/items/{first}/discard")[0] == 200)
        check("restore", call("POST", f"/items/{first}/restore")[0] == 200)
        check("unknown action", call("POST", f"/items/{first}/explode")[0] == 404)
        check("foreign item", call("POST", "/items/999999/discard")[0] == 404)
        call("POST", f"/items/{second}/discard")
        check("empty trash", call("POST", f"/projects/{project}/trash/empty")[0] == 200)

        # --- a second account must see and change nothing of the first (optional EMAIL2 PASSWORD2) ---
        if len(sys.argv) > 5:
            email2, password2 = sys.argv[4], sys.argv[5]
            other = urllib.request.build_opener(NoRedirect, urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            check("second account logs in", call("POST", "/login", {"email": email2, "password": password2}, who=other)[0] == 303)
            _, _, theirs = call("GET", "/", who=other)
            check("second account sees no project of the first", "Integration" not in theirs and email not in theirs)
            check("foreign project page is 404", call("GET", f"/projects/{project}", who=other)[0] == 404)
            for action in ("accept", "reject", "discard", "restore", "delete"):
                check(f"foreign item {action} is 404", call("POST", f"/items/{first}/{action}", who=other)[0] == 404)
            check("foreign reorder refused", call("POST", "/items/reorder", {"kind": "bug", "ids": [int(first)]}, True, who=other)[0] == 400)
            check("foreign project cannot be moved", call("POST", "/projects/move", {"id": int(project), "page": 1, "index": 0}, True, who=other)[0] == 400)
            call("POST", f"/items/{first}", {"title": "hacked"}, who=other)
            call("POST", f"/projects/{project}/items", {"kind": "bug", "title": "planted"}, who=other)
            check("foreign trash cannot be emptied", call("POST", f"/projects/{project}/trash/empty", who=other)[0] == 200)
            check("foreign delete is 404", call("POST", f"/projects/{project}/delete", {"password": password2}, who=other)[0] == 404)
            _, _, mine = call("GET", f"/projects/{project}")
            check("first account's data is untouched", "Renamed" in mine and "hacked" not in mine and "planted" not in mine)
            check("normal user has no user management", call("GET", "/users", who=other)[0] == 404
                  and call("POST", "/users/add", {"email": "x@example.com"}, who=other)[0] == 403
                  and call("POST", "/users/1/owner", {"confirm": password2}, who=other)[0] == 403
                  and call("POST", "/users/1/delete", {"confirm": password2}, who=other)[0] == 403)
            check("second account logs out", call("POST", "/logout", who=other)[0] == 303)
            check("its session is gone, the first one still works", call("GET", "/", who=other)[0] == 303
                  and call("GET", "/")[0] == 200)

    # --- delete needs the password ---
    check("delete wrong password", call("POST", f"/projects/{project}/delete", {"password": "nope"})[0] == 403)
    check("delete", call("POST", f"/projects/{project}/delete", {"password": password})[0] == 200)
    check("deleted", call("GET", f"/projects/{project}")[0] == 404)

# --- settings and logout -------------------------------------------------------------------
check("settings", call("POST", "/settings", {"display_name": "Tester", "language": "en"})[0] == 303)
check("language applied", "Log out" in call("GET", "/")[2])
call("POST", "/settings", {"display_name": "", "language": "de"})
check("theme saved", call("POST", "/theme", {"value": "dark"})[0] == 200
      and 'data-theme-saved="dark"' in call("GET", "/")[2])
check("bad theme refused", call("POST", "/theme", {"value": "neon"})[0] == 400)
check("theme needs login", call("POST", "/theme", {"value": "dark"}, cookies=False)[0] == 401)
call("POST", "/theme", {"value": "light"})
check("logout", call("POST", "/logout")[0] == 303)
check("session gone", call("GET", "/")[0] == 303)

print(f"\n{len(failures)} failed" if failures else "\nall passed")
sys.exit(1 if failures else 0)
