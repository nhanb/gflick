import json
import secrets
import time
from contextlib import closing
from string import Template
from urllib.parse import quote, unquote

# Explicit names so I don't mistake between `requests` and bottle's `request`
from requests import get as requests_get
from requests import head as requests_head
from requests import post as requests_post

from bottle import HTTPError, HTTPResponse, request, response, route, run

from . import db

PORT = 8000
CHUNK_SIZE = 1024 * 1024 * 2  # 2MB in bytes

with open("tokens.json", "r") as tfile:
    tokens = json.load(tfile)

CLIENT_ID = tokens["client_id"]
CLIENT_SECRET = tokens["client_secret"]
REFRESH_TOKEN = tokens["refresh_token"]
USER_PASSWORD = tokens["user_password"]
USER_TOKEN = secrets.token_urlsafe(128)


def get_access_token(clientId: str, clientSecret: str, refreshToken: str) -> str:
    print("Refreshing access token")
    start_time = time.time()

    r = requests_post(
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
    expiration = start_time + rjson["expires_in"]

    print(f"Got access token: {token[:15]}[...]")
    return token, expiration


def get_token():
    """
    Refreshes token if not set or about to expire.
    Returns usable token if succeeded, otherwise None.
    """
    should_refresh = False
    token_text = db.keyval_get("gdrive_access_token")

    if not token_text:
        print("Token not found in db")
        should_refresh = True
    else:
        token_json = json.loads(token_text)
        expiration = token_json["expiration"]
        token = token_json["token"]
        if expiration <= time.time() + 30:
            print(f"Token {token[:15]}[...] about to expire")
            should_refresh = True
        else:
            print(f"Reusing token {token[:15]}[...]")

    if should_refresh:
        token, expiration = get_access_token(CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN)
        if token:
            db.keyval_set(
                "gdrive_access_token",
                json.dumps({"token": token, "expiration": expiration}),
            )
        else:
            return None

    return token


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


html_template_str = """
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
</script>
<style>
html {
  font-size: 100%;
  line-height: 1.5em;
}

p {
  background-color: #eee;
  padding: 0.5em;
  border: 1px solid #ccc;
  border-radius: 2px;
  overflow-wrap: break-word;
  margin: 0 0 0.8em 0;
}
</style>
</html>
"""


def page_html(title, body):
    return Template(html_template_str).substitute(title=title, body=body)


@route("/", method="GET")
def view_index():
    token = get_token()
    if not token:
        return HTTPError(500, "FAILED")

    api_resp = requests_get(
        "https://www.googleapis.com/drive/v3/drives",
        headers={"Authorization": f"Bearer {token}"},
    )

    drives = api_resp.json()["drives"]
    drives_html = "\n".join(
        f'<p><a href="/d/{d["id"]}">{d["name"]}</a></p>' for d in drives
    )
    html = page_html("GFlick Home", drives_html)
    return html


@route("/slug/<file_id>/<file_name>", method="GET")
def view_slug(file_id, file_name):
    file_name = unquote(file_name)

    slug = db.get_or_create_link(file_id)

    html = page_html(
        "View file",
        "<div>This is a <strong>publicly accessible</strong> direct link:</div>"
        f'<a href="/v/{slug}/{quote(file_name)}">{file_name}</a>',
    )
    return html


@route("/v/<file_slug>/<file_name>", method=["GET", "HEAD"])
def view_video(file_slug, file_name):
    file_id = db.get_file_id(file_slug)
    if not file_id:
        return HTTPError(404, "Nothing to see here.")

    print(f"{request.method} request headers:")
    for k, v in request.headers.items():
        print(f"  {k}: {v}")

    token = get_token()
    if not token:
        return HTTPError(500, "FAILED")

    req_headers = {}
    req_headers["Authorization"] = f"Bearer {token}"
    if "Range" in request.headers:
        req_headers["Range"] = request.headers["Range"]

    url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"

    if request.method == "GET":
        request_func = requests_get
    elif request.method == "HEAD":
        request_func = requests_head

    with closing(request_func(url, headers=req_headers, stream=True)) as vid_resp:
        gflick_resp_headers = {}

        if not 200 <= vid_resp.status_code <= 299:  # known cases: 200, 206
            return HTTPError(vid_resp.status_code, "FAILED")

        # VLC android won't allow seeking if accept-ranges isn't found (?)
        gflick_resp_headers["Accept-Ranges"] = "bytes"

        for hkey, hval in vid_resp.headers.items():
            # The http library (urllib3) already "unchunked" the response stream,
            # so forwarding `Transfer-Encoding: chunked` as-is to end user will
            # result in error. Therefore, let's skip it:
            if (hkey, hval) == ("Transfer-Encoding", "chunked"):
                print("Skipped", hkey, hval)
                continue
            gflick_resp_headers[hkey] = hval

        if request.method == "HEAD":
            return HTTPResponse(200, headers=gflick_resp_headers)

        # is GET request => let's stream response body
        for hkey, hval in gflick_resp_headers.items():
            response.headers.replace(hkey, hval)
        try:
            for chunk in vid_resp.raw.stream(CHUNK_SIZE):
                yield chunk

        except (ConnectionResetError, BrokenPipeError):
            print(f"Client '{request.headers.get('User-Agent', '')}' aborted request")


@route("/d/<drive_id>", method="GET")
@route("/d/<drive_id>/<folder_id>", method="GET")
def view_drive(drive_id, folder_id=None):
    token = get_token()
    if not token:
        return HTTPError(500, "FAILED")

    parent = folder_id or drive_id
    api_resp = requests_get(
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

    files = api_resp.json()["files"]
    files_html = "\n".join(file_html(drive_id, d) for d in files)
    html = page_html(title=parent, body=files_html)
    return html


@route("/login", method=["GET", "POST"])
def view_login():
    pass


def run_dev():
    gunicorn_kwargs = {"workers": 5, "reload": True, "debug": True}
    run(server="gunicorn", host="localhost", port=8000, **gunicorn_kwargs)


def run_prod():
    gunicorn_kwargs = {"workers": 5}
    run(server="gunicorn", host="localhost", port=8000, **gunicorn_kwargs)
