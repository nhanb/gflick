import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import urllib3

CLIENT_ID = os.environ["GFLICK_ID"]
CLIENT_SECRET = os.environ["GFLICK_SECRET"]
REFRESH_TOKEN = os.environ["GFLICK_REFRESH"]

CHUNK_SIZE = 1024 * 1024 * 2  # 2MB in bytes


def getAccessToken(http, clientId: str, clientSecret: str, refreshToken: str) -> str:
    r = http.request(
        "POST",
        "https://www.googleapis.com/oauth2/v4/token",
        headers={"Accept": "application/json"},
        fields={
            "client_id": clientId,
            "client_secret": clientSecret,
            "refresh_token": refreshToken,
            "grant_type": "refresh_token",
        },
    )

    if r.status != 200:
        print("\nGet token failed:")
        print(r.status)
        print(r.data, "\n")
        return None

    return json.loads(r.data.decode("utf-8"))["access_token"]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        videoId = "1FeZu-LUFI6Kf3pl2AjyVUdqwgDxd0KRq"
        # TODO: need setup-teardown middleware to cleanly create and clear connection pool

        # Setup
        http = urllib3.PoolManager()

        token = getAccessToken(http, CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN)
        if token is None:
            http.clear()
            return "ERR"

        # req_headers = {key: val for key, val in self.headers.items()}
        req_headers = {}
        req_headers["Authorization"] = f"Bearer {token}"
        if "Range" in self.headers:
            req_headers["Range"] = self.headers["Range"]

        url = f"https://www.googleapis.com/drive/v3/files/{videoId}?alt=media"
        vid_resp = http.request("GET", url, headers=req_headers, preload_content=False)

        if vid_resp.status != 200:
            self.send_response(vid_resp.status, "FAILED")
        else:
            self.send_response(200, "OK LAH")

        for hkey, hval in vid_resp.headers.items():
            print(">", hkey, ":", hval)
            self.send_header(hkey, hval)
        self.end_headers()

        for chunk in vid_resp.stream(CHUNK_SIZE):
            self.wfile.write(chunk)

        vid_resp.release_conn()

        # Teardown
        http.clear()

    def do_HEAD(self):
        self.send_response(200, "OKLAH")
        self.end_headers()
        pass


def run(server_class=ThreadingHTTPServer, handler_class=Handler):
    server_address = ("", 8080)
    httpd = server_class(server_address, handler_class)
    httpd.serve_forever()


print("Running")
run()
