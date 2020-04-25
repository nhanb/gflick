import os
import re
from contextlib import closing
from datetime import datetime, timedelta
from enum import Enum, unique
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

PORT = 8000
CHUNK_SIZE = 1024 * 1024 * 2  # 2MB in bytes

CLIENT_ID = os.environ["GFLICK_ID"]
CLIENT_SECRET = os.environ["GFLICK_SECRET"]
REFRESH_TOKEN = os.environ["GFLICK_REFRESH"]

_ACCESS_TOKEN = None


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


def refresh_token_if_necessary(expiries={}):
    """
    Refreshes token if not set or about to expire.
    Returns usable token if succeeded, otherwise None.
    """
    global _ACCESS_TOKEN

    should_refresh = False

    if not _ACCESS_TOKEN:
        print("Token not found")
        should_refresh = True

    elif expiries.get(_ACCESS_TOKEN) <= datetime.now() + timedelta(seconds=30):
        print(f"Token {_ACCESS_TOKEN[:15]}[...] about to expire")
        should_refresh = True

    else:
        print(f"Reusing token {_ACCESS_TOKEN[:15]}[...]")

    if should_refresh:
        _ACCESS_TOKEN, expiration = get_access_token(
            CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN
        )
        if _ACCESS_TOKEN:
            expiries[_ACCESS_TOKEN] = expiration
        else:
            return None

    return _ACCESS_TOKEN


# This server only serves GET and HEAD requests
@unique
class Http(Enum):
    GET = "GET"
    HEAD = "HEAD"


class Handler(BaseHTTPRequestHandler):
    def serve_video(self, http_method: Http, videoId):

        print(f"{http_method} request headers:")
        for k, v in self.headers.items():
            print(f"  {k}: {v}")

        token = refresh_token_if_necessary()

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

    routes = {re.compile(r"^/v/([\w\-]+)/?$"): serve_video}

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
