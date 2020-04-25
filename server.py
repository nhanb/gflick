import json
import re
from contextlib import closing
from datetime import datetime, timedelta
from enum import Enum, unique
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from string import Template

import requests

PORT = 8000
CHUNK_SIZE = 1024 * 1024 * 2  # 2MB in bytes

with open("tokens.json", "r") as tfile:
    tokens = json.load(tfile)

CLIENT_ID = tokens["client_id"]
CLIENT_SECRET = tokens["client_secret"]
REFRESH_TOKEN = tokens["refresh_token"]
ACCESS_TOKEN = None


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


def file_html(drive_id, data):
    if data["mimeType"] == "application/vnd.google-apps.folder":
        return f'<li><a href="/d/{drive_id}/{data["id"]}">{data["name"]}</a></li>'
    else:
        return f'<li><a href="/v/{data["id"]}">{data["name"]}</a></li>'


def page_html(title, body):
    return Template(
        """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>$title</title>
</head>
<body>
    $body
</body>
</html>
"""
    ).substitute(title=title, body=body)


class Handler(BaseHTTPRequestHandler):
    def serve_drive(self, http_method: Http, drive_id, folder_id=None):
        if http_method == Http.HEAD:
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
                "driveId": drive_id,
                "corpora": "drive",
                "includeItemsFromAllDrives": True,
                "supportsAllDrives": True,
                "orderBy": "name",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert api_resp.status_code == 200, api_resp.text

        self.send_response(200, "OK")
        self.send_header("Content-Type", "text/html")
        self.end_headers()

        files = api_resp.json()["files"]
        files_html = "\n".join(file_html(drive_id, d) for d in files)
        html = page_html(parent, f"<ul>{files_html}</ul>")
        self.wfile.write(html.encode())

    def serve_drives(self, http_method: Http):
        if http_method == Http.HEAD:
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
            f'<li><a href="/d/{d["id"]}">{d["name"]}</a></li>' for d in drives
        )
        self.wfile.write(f"<ul>{drives_html}</ul>".encode())

    def serve_video(self, http_method: Http, videoId):

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

        url = f"https://www.googleapis.com/drive/v3/files/{videoId}?alt=media"

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
                self.send_header(hkey, hval)

            self.end_headers()

            if http_method == Http.HEAD:
                return

            # is GET request => let's stream response body
            try:
                for chunk in vid_resp.iter_content(CHUNK_SIZE):
                    self.wfile.write(chunk)
            except (ConnectionResetError, BrokenPipeError):
                print(f"Client '{self.headers.get('User-Agent', '')}' aborted request")

    # ROUTING LOGIC FOLLOWS

    routes = {
        re.compile(r"^/v/([\w\-]+)/?$"): serve_video,
        re.compile(r"^/$"): serve_drives,
        re.compile(r"^/d/([\w\-]+)/?$"): serve_drive,
        re.compile(r"^/d/([\w\-]+)/([\w\-]+)/?$"): serve_drive,
    }

    def route(self, http_method: Http):
        assert http_method in [Http.GET, Http.HEAD]

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


def run(server_class=ThreadingHTTPServer, handler_class=Handler):
    server_address = ("", PORT)
    httpd = server_class(server_address, handler_class)
    httpd.serve_forever()


print(f"Running at port {PORT}")
run()
