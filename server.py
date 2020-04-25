import os
import re
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

PORT = 8000
CHUNK_SIZE = 1024 * 1024 * 2  # 2MB in bytes

CLIENT_ID = os.environ["GFLICK_ID"]
CLIENT_SECRET = os.environ["GFLICK_SECRET"]
REFRESH_TOKEN = os.environ["GFLICK_REFRESH"]

ACCESS_TOKEN = None


def getAccessToken(clientId: str, clientSecret: str, refreshToken: str) -> str:
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

    return r.json()["access_token"]


class Handler(BaseHTTPRequestHandler):
    def serve_video(self, videoId):
        print("Request headers:")
        for k, v in self.headers.items():
            print(f"  {k}: {v}")

        global ACCESS_TOKEN

        if not ACCESS_TOKEN:
            ACCESS_TOKEN = getAccessToken(CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN)

        if not ACCESS_TOKEN:
            self.send_response(500, "FAILED")
            self.end_headers()
            return

        req_headers = {}
        req_headers["Authorization"] = f"Bearer {ACCESS_TOKEN}"
        if "Range" in self.headers:
            req_headers["Range"] = self.headers["Range"]

        url = f"https://www.googleapis.com/drive/v3/files/{videoId}?alt=media"

        with closing(requests.get(url, headers=req_headers, stream=True)) as vid_resp:
            if vid_resp.status_code != 200:
                self.send_response(vid_resp.status_code, "FAILED")
            else:
                self.send_response(200, "OK")
                # VLC android won't allow seeking if accept-ranges isn't found (?)
                self.send_header("Accept-Ranges", "bytes")

            for hkey, hval in vid_resp.headers.items():
                self.send_header(hkey, hval)

            self.end_headers()

            for chunk in vid_resp.iter_content(CHUNK_SIZE):
                self.wfile.write(chunk)

    routes = {re.compile(r"^/v/([\w\-]+)/?$"): serve_video}

    def do_GET(self):
        for pattern, handler in self.routes.items():
            match = pattern.match(self.path)
            if match:
                handler(self, *match.groups())
                return

        self.send_response(404, "NOT FOUND")
        self.end_headers()
        self.wfile.write(b"Nothing to see here.")

    def do_HEAD(self):
        self.send_response(200, "OKLAH")
        self.end_headers()


def run(server_class=ThreadingHTTPServer, handler_class=Handler):
    server_address = ("", PORT)
    httpd = server_class(server_address, handler_class)
    httpd.serve_forever()


print(f"Running at port {PORT}")
run()
