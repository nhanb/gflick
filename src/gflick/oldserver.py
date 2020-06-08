import base64
import json
import re
import secrets
import time
from contextlib import closing
from datetime import datetime, timedelta
from enum import Enum, unique
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from string import Template
from urllib.parse import parse_qs, quote, unquote

import requests

from . import db

PORT = 8000
CHUNK_SIZE = 1024 * 1024 * 2  # 2MB in bytes

with open("tokens.json", "r") as tfile:
    tokens = json.load(tfile)

CLIENT_ID = tokens["client_id"]
CLIENT_SECRET = tokens["client_secret"]
REFRESH_TOKEN = tokens["refresh_token"]
ACCESS_TOKEN = None

USER_PASSWORD = tokens["user_password"]
USER_TOKEN = secrets.token_urlsafe(128)


def get_access_token(clientId: str, clientSecret: str, refreshToken: str) -> str:
    print("Refreshing access token")
    start_time = datetime.now()

    r = requests.post(
        "https://www.googleapis.com/oauth2/v4/token",
        headers={"Accept": "application/json"},
        data={
            "client_id": clientId,
            "client_secret": clientSecret,
            "refresh_token": refreshToken,
            "grant_type": "refresh_token",
        },
    )

    if r.status_code != 200:
        print("\nGet token failed:")
        print(r.status_code)
        print(r.data, "\n")
        return None

    rjson = r.json()
    token = rjson["access_token"]
    expiration = start_time + timedelta(seconds=rjson["expires_in"])

    print(f"Got access token: {token[:15]}[...]")
    return token, expiration


def get_token(expiries={}):
    """
    Refreshes token if not set or about to expire.
    Returns usable token if succeeded, otherwise None.
    """
    global ACCESS_TOKEN

    should_refresh = False

    if not ACCESS_TOKEN:
        print("Token not found")
        should_refresh = True

    elif expiries.get(ACCESS_TOKEN) <= datetime.now() + timedelta(seconds=30):
        print(f"Token {ACCESS_TOKEN[:15]}[...] about to expire")
        should_refresh = True

    else:
        print(f"Reusing token {ACCESS_TOKEN[:15]}[...]")

    if should_refresh:
        ACCESS_TOKEN, expiration = get_access_token(
            CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN
        )
        if ACCESS_TOKEN:
            expiries[ACCESS_TOKEN] = expiration
        else:
            return None

    return ACCESS_TOKEN


# This server only serves GET and HEAD requests
@unique
class Http(Enum):
    GET = "GET"
    HEAD = "HEAD"
    POST = "POST"


def file_html(drive_id, data):
    if data["mimeType"] == "application/vnd.google-apps.folder":
        return f'<p>&#128193;&nbsp;<a href="/d/{drive_id}/{data["id"]}">{data["name"]}</a></p>'
    else:
        filename = quote(data["name"])
        inner_text = data["name"]
        thumbnail_link = data.get("thumbnailLink")
        if thumbnail_link:
            inner_text = f'<img src="{thumbnail_link}" /><br/>{inner_text}'
        return f'<p><a href="/slug/{data["id"]}/{filename}">{inner_text}</a></p>'


js = ""
css = ""
with open("script.js", "r") as jsfile:
    js = jsfile.read()
with open("style.css", "r") as cssfile:
    css = cssfile.read()
html_template_str = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>$title</title>
</head>
<body>
    $body
</body>
<script>
$server_provided_js
{js}
</script>
<style>{css}</style>
</html>
"""


def page_html(title, body, username="", password=""):
    server_provided_js = f"""
    const username = '{username}';
    const password = '{password}';
    """
    return Template(html_template_str).substitute(
        title=title, body=body, js=js, css=css, server_provided_js=server_provided_js
    )


class Handler(BaseHTTPRequestHandler):
    def serve_drive(self, http_method: Http, drive_id, folder_id=None):
        if http_method != Http.GET:
            self.send_response(405, "METHOD NOT SUPPORTED")
            self.end_headers()
            return

        token = get_token()
        if not token:
            self.send_response(500, "FAILED")
            self.end_headers()
            return

        parent = folder_id or drive_id
        api_resp = requests.get(
            "https://www.googleapis.com/drive/v3/files",
            params={
                "q": f"'{parent}' in parents",
                "fields": "files(id,name,mimeType,thumbnailLink)",
                "driveId": drive_id,
                "corpora": "drive",
                "includeItemsFromAllDrives": True,
                "supportsAllDrives": True,
                "orderBy": "folder,name,createdTime desc",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert api_resp.status_code == 200, api_resp.text

        self.send_response(200, "OK")
        self.send_header("Content-Type", "text/html")
        self.end_headers()

        # Read basicauth username & password back from header,
        # pass them to frontend as javascript consts. See page_html().
        username = ""
        password = ""
        auth_header = self.headers.get("authorization")
        if auth_header and auth_header.startswith("Basic "):
            encoded = auth_header[6:]
            username, password = base64.b64decode(encoded).decode().split(":")

        files = api_resp.json()["files"]
        files_html = "\n".join(file_html(drive_id, d) for d in files)
        html = page_html(
            title=parent, body=files_html, username=username, password=password,
        )
        self.wfile.write(html.encode())

    def serve_drives(self, http_method: Http):
        if http_method != Http.GET:
            self.send_response(405, "METHOD NOT SUPPORTED")
            self.end_headers()
            return

        token = get_token()
        if not token:
            self.send_response(500, "FAILED")
            self.end_headers()
            return

        api_resp = requests.get(
            "https://www.googleapis.com/drive/v3/drives",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert api_resp.status_code == 200, api_resp.text

        self.send_response(200, "OK")
        self.send_header("Content-Type", "text/html")
        self.end_headers()

        drives = api_resp.json()["drives"]
        drives_html = "\n".join(
            f'<p><a href="/d/{d["id"]}">{d["name"]}</a></p>' for d in drives
        )
        html = page_html("GFlick Home", drives_html)
        self.wfile.write(html.encode())

    def serve_generate_slug(self, http_method: Http, file_id, file_name):
        file_name = unquote(file_name)

        if http_method != Http.GET:
            self.send_response(405, "METHOD NOT SUPPORTED")
            self.end_headers()
            return

        slug = db.get_or_create_link(file_id)

        self.send_response(200, "OK")
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(
            page_html(
                "View file",
                "<div>This is a <strong>publicly accessible</strong> direct link:</div>"
                f'<a href="/v/{slug}/{quote(file_name)}">{file_name}</a>',
            ).encode()
        )

        # self.send_response(303, "See Other")
        # self.send_header("Location", f"/v/{slug}/{file_name}")
        # self.end_headers()

    def serve_video(self, http_method: Http, video_slug):
        if http_method not in [Http.GET, Http.HEAD]:
            self.send_response(405, "METHOD NOT SUPPORTED")
            self.end_headers()
            return

        file_id = db.get_file_id(video_slug)
        if not file_id:
            self.send_response(404, "Nothing to see here.")
            self.end_headers()
            return

        print(f"{http_method} request headers:")
        for k, v in self.headers.items():
            print(f"  {k}: {v}")

        token = get_token()

        if not token:
            self.send_response(500, "FAILED")
            self.end_headers()
            return

        req_headers = {}
        req_headers["Authorization"] = f"Bearer {token}"
        if "Range" in self.headers:
            req_headers["Range"] = self.headers["Range"]

        url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"

        if http_method == Http.GET:
            request_func = requests.get
        elif http_method == Http.HEAD:
            request_func = requests.head

        with closing(request_func(url, headers=req_headers, stream=True)) as vid_resp:
            if vid_resp.status_code != 200:
                self.send_response(vid_resp.status_code, "FAILED")
            else:
                self.send_response(200, "OK")
                # VLC android won't allow seeking if accept-ranges isn't found (?)
                self.send_header("Accept-Ranges", "bytes")

            for hkey, hval in vid_resp.headers.items():
                # The http library (urllib3) already "unchunked" the response stream,
                # so forwarding `Transfer-Encoding: chunked` as-is to end user will
                # result in error. Therefore, let's skip it:
                if (hkey, hval) == ("Transfer-Encoding", "chunked"):
                    print("Skipped", hkey, hval)
                    continue
                self.send_header(hkey, hval)

            self.end_headers()

            if http_method == Http.HEAD:
                return

            # is GET request => let's stream response body
            try:
                for chunk in vid_resp.raw.stream(CHUNK_SIZE):
                    self.wfile.write(chunk)
            except (ConnectionResetError, BrokenPipeError):
                print(f"Client '{self.headers.get('User-Agent', '')}' aborted request")

    def serve_login_form(self, method):
        if method in (Http.GET, Http.HEAD):
            self.send_response(200, "OK")
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            if method == Http.GET:
                self.wfile.write(
                    page_html(
                        title="Login first!",
                        body="""
<form action="/login" method="post">
    <label for="name">Enter password:</label>
    <input type="password" name="password" id="password" required autofocus />
    <input type="submit" value="Login" />
</form>""",
                    ).encode()
                )

        elif method == Http.POST:
            content_len = int(self.headers.get("Content-Length"))
            post_body = self.rfile.read(content_len).decode()
            try:
                password = parse_qs(post_body)["password"][0]
                assert password == USER_PASSWORD
            except Exception:
                self.send_response(400, "Invalid password")
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                import traceback

                traceback.print_exc()
                self.wfile.write("Invalid password".encode())

                # Prevents lazy brute force attacks,
                # Probably not effective until proper rate limiting is implemented.
                time.sleep(5)
                return

            # Password is correct!
            self.send_response(302, "Invalid password")
            self.send_header("Set-Cookie", f"user_token={USER_TOKEN}; Path=/")
            self.send_header("Location", "/")
            self.end_headers()

    # ROUTING LOGIC FOLLOWS

    routes = {
        re.compile(r"^/slug/([\w\-]+)/(.+)/?$"): serve_generate_slug,
        re.compile(r"^/v/([\w\-]+)/.+/?$"): serve_video,
        re.compile(r"^/$"): serve_drives,
        re.compile(r"^/d/([\w\-]+)/?$"): serve_drive,
        re.compile(r"^/d/([\w\-]+)/([\w\-]+)/?$"): serve_drive,
        re.compile(r"^/login/?$"): serve_login_form,
    }

    def route(self, http_method: Http):
        assert http_method in [Http.GET, Http.HEAD, Http.POST]

        if not self.path.startswith("/v/") and not self.check_auth():
            return

        for pattern, handler in self.routes.items():
            match = pattern.match(self.path)
            if match:
                handler(self, http_method, *match.groups())
                return True

        self.send_response(404, "NOT FOUND")
        self.end_headers()

        if http_method == Http.GET:
            self.wfile.write(b"Route not found")

    def do_GET(self):
        self.route(Http.GET)

    def do_HEAD(self):
        self.route(Http.HEAD)

    def do_POST(self):
        self.route(Http.POST)

    def check_auth(self):
        cookie = SimpleCookie()
        cookie.load(self.headers.get("cookie", ""))

        token = cookie.get("user_token")

        if (not token or token.value != USER_TOKEN) and not self.path.startswith(
            "/login"
        ):
            self.send_response(302, "Moved Temporarily")
            self.send_header("Location", "/login")
            self.send_header("Set-Cookie", "user_token=; Path=/")
            self.end_headers()
            return False

        return True


def run(server_class=ThreadingHTTPServer, handler_class=Handler):
    db.init()
    db.delete_old_links()

    server_address = ("", PORT)
    httpd = server_class(server_address, handler_class)
    httpd.serve_forever()


print(f"Running at port {PORT}")
run()
