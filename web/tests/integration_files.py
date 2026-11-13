"""End-to-end test of the file storage over HTTP (not part of the unit tests).

    python tests/integration_files.py http://127.0.0.1:8001 EMAIL PASSWORD PROJECT_ID

Run against a throwaway instance with its own database (see PROJEKT.md, "Tests"). Uploads a file in chunks,
reads it back (also a byte range, as a video player does), checks the headers and that a second login is
refused, then deletes everything it made.
"""
import http.cookiejar
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

base, email, password, project = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3], sys.argv[4]
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
failures = []


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def call(path, data=None, method=None, headers=None, client=None):
    request = urllib.request.Request(base + path, data=data, method=method, headers=headers or {})
    try:
        with (client or opener).open(request) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read()
    except urllib.error.HTTPError as problem:
        return problem.code, {k.lower(): v for k, v in problem.headers.items()}, problem.read()


def form(**values):
    return urllib.parse.urlencode(values).encode()


def check(label, condition, detail=""):
    print(("ok   " if condition else "FAIL ") + label + (f"  {detail}" if not condition else ""))
    if not condition:
        failures.append(label)


quiet = urllib.request.build_opener(NoRedirect, urllib.request.HTTPCookieProcessor(jar))
status, _, _ = call("/login", form(email=email, password=password), client=quiet)
check("login", status in (302, 303), status)

payload = bytes(range(256)) * 3000                      # 768,000 bytes
status, _, body = call(f"/projects/{project}/files/start", form(name="clip.mp4", size=len(payload)))
info = json.loads(body)
check("start upload", status == 200 and info["ok"] and info["category"] == "media", body)
fid = info["id"]

step = 300_000
for offset in range(0, len(payload), step):
    status, _, body = call(f"/files/{fid}/chunk?offset={offset}", payload[offset:offset + step], "POST",
                           {"Content-Type": "application/octet-stream"})
    check(f"chunk at {offset}", status == 200 and json.loads(body)["size"] == min(offset + step, len(payload)), body)
status, _, body = call(f"/files/{fid}/chunk?offset=5", b"zz", "POST")
check("chunk at a wrong offset is refused", status == 409, status)
status, _, body = call(f"/files/{fid}/finish", b"", "POST")
check("finish", status == 200 and json.loads(body)["size"] == len(payload), body)

status, headers, body = call(f"/files/{fid}")
check("download is the same bytes", status == 200 and body == payload, status)
check("type from the fixed table, shown inline", headers.get("content-type") == "video/mp4"
      and headers.get("content-disposition", "").startswith("inline"), headers)
check("nosniff and sandbox", headers.get("x-content-type-options") == "nosniff"
      and "sandbox" in headers.get("content-security-policy", ""), headers)
status, headers, body = call(f"/files/{fid}", headers={"Range": "bytes=1000-1999"})
check("byte range (video player)", status == 206 and body == payload[1000:2000], status)

status, _, body = call(f"/projects/{project}/files/start", form(name="page.html", size=5))
html = json.loads(body)["id"]
call(f"/files/{html}/chunk?offset=0", b"<h1/>", "POST")
call(f"/files/{html}/finish", b"", "POST")
status, headers, _ = call(f"/files/{html}")
check("html is a download, not a page", headers.get("content-type") == "application/octet-stream"
      and headers.get("content-disposition", "").startswith("attachment"), headers)

status, _, body = call(f"/projects/{project}/links", form(url="https://example.org/doc", name="Doc"))
link = json.loads(body)
check("add link", status == 200 and link["category"] == "links", body)
status, _, body = call(f"/projects/{project}/links", form(url="javascript:alert(1)"))
check("a script address is refused", status == 400, status)

anonymous = urllib.request.build_opener(NoRedirect)
status, _, _ = call(f"/files/{fid}", client=anonymous)
check("no login, no file", status == 401, status)

for item in (fid, html, link["id"]):
    status, _, _ = call(f"/files/{item}/delete", b"", "POST")
    check(f"delete {item}", status == 200, status)
status, _, _ = call(f"/files/{fid}")
check("gone after delete", status == 404, status)

print("FAILED: " + ", ".join(failures) if failures else "all fine")
sys.exit(1 if failures else 0)
