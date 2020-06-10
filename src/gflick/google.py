import json
import os
import socketserver
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

"""
Helper script to quickly get user consent for GDrive API access.
Simply run `python google.py` and follow instructions.
"""

TOKENS_FILE = "tokens.json"

CLIENT_ID = os.environ.get("CLIENT_ID") or input("CLIENT_ID: ").strip()
CLIENT_SECRET = os.environ.get("CLIENT_SECRET") or input("CLIENT_SECRET: ").strip()
USER_PASSWORD = os.environ.get("USER_PASSWORD") or input("USER_PASSWORD: ").strip()


def main():
    handler = wait_for_authorization_code()
    redirect_port = next(handler)
    oauth_url = build_oauth_url(redirect_port)
    webbrowser.open_new_tab(oauth_url)
    authorization_code = next(handler)
    tokens = get_initial_tokens(authorization_code, redirect_port)
    tokens["authorization_code"] = authorization_code
    tokens["client_id"] = CLIENT_ID
    tokens["client_secret"] = CLIENT_SECRET
    tokens["user_password"] = USER_PASSWORD
    with open(TOKENS_FILE, "w") as tfile:
        tfile.write(json.dumps(tokens, indent=2, sort_keys=True))
    print(f"Results written to {TOKENS_FILE}")


def wait_for_authorization_code():
    """
    Returns a generator that yields twice:
        - first, the sucessfully bound port - use this to construct `redirect_uri`
        - second, the actual authorization code

    Example:
        handler = wait_for_authorization_code()
        port = next(handler)
        <give user oauth url>
        authorization_code = next(handler)  # will block here until user consents

    https://developers.google.com/identity/protocols/OAuth2InstalledApp#step-2:-send-a-request-to-googles-oauth-2.0-server
    """

    # Prepare a quick http server that serves one GET request
    class OneTimeHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(
                b"Sucesssfully authorized. You can close this browser tab now."
            )
            self.server.google_auth_response = self.path

    with socketserver.TCPServer(("", 0), OneTimeHandler) as server:
        port = server.socket.getsockname()[1]
        yield port
        print(f"Serving at port {port}. Check your browser.")
        server.handle_request()
        google_auth_response = server.google_auth_response

    yield _get_code_from_response(google_auth_response)


def _get_code_from_response(google_auth_response):
    # auth response is in the form of GET params, so let's parse them:
    params = parse_qs(urlparse(google_auth_response).query)
    if "code" in params:
        return params["code"][0]
    else:
        raise Exception(f"Failed to get authorization code: {params['error']}")


def build_oauth_url(redirect_port):
    base_url = "https://accounts.google.com/o/oauth2/auth"
    params = {
        "access_type": "offline",
        "client_id": CLIENT_ID,
        "redirect_uri": f"http://127.0.0.1:{redirect_port}",
        "response_type": "code",
        "scope": (
            "https://www.googleapis.com/auth/drive"
            " https://www.googleapis.com/auth/drive.metadata"
        ),
        "state": str(uuid.uuid4()),  # we probably don't need to use this?
    }
    return f"{base_url}?{urlencode(params)}"


def get_initial_tokens(authorization_code, redirect_port):
    endpoint = "https://www.googleapis.com/oauth2/v4/token"
    params = {
        "code": authorization_code,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "redirect_uri": f"http://127.0.0.1:{redirect_port}",
    }
    resp = httpx.post(endpoint, data=params)
    assert resp.status_code == 200, f"Failed to get initial tokens: {resp.text}"

    resp_json = resp.json()
    return {
        "refresh_token": resp_json["refresh_token"],
        "access_token": resp_json["access_token"],
    }


def get_access_token(refresh_token):
    endpoint = "https://oauth2.googleapis.com/token"
    params = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    resp = httpx.post(endpoint, data=params)
    assert resp.status_code == 200, "Failed to get access token"

    resp_json = resp.json()
    return {
        "access_token": resp_json["access_token"],
        "expires_in": resp_json["expires_in"],
    }


if __name__ == "__main__":
    main()
