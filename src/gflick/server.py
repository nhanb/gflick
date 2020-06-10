import json
import os
import secrets
import time
from string import Template
from urllib.parse import parse_qs, quote, unquote

import httpx
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse, Response, StreamingResponse
from starlette.routing import Route

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


async def get_access_token(
    httpx_client, clientId: str, clientSecret: str, refreshToken: str
) -> str:
    print("Refreshing access token")
    start_time = time.time()

    r = await httpx_client.post(
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


async def get_token(httpx_client):
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
        token, expiration = await get_access_token(
            httpx_client, CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN
        )
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
    <link rel="shortcut icon" href="data:image/x-icon;," type="image/x-icon" />
</head>

<body>$body</body>

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


async def view_index(req):
    token = await get_token(req.app.state.httpx_client)
    if not token:
        return Response("FAILED", status_code=500)

    api_resp = await req.app.state.httpx_client.get(
        "https://www.googleapis.com/drive/v3/drives",
        headers={"Authorization": f"Bearer {token}"},
    )

    drives = api_resp.json()["drives"]
    drives_html = "\n".join(
        f'<p><a href="/d/{d["id"]}">{d["name"]}</a></p>' for d in drives
    )
    html = page_html("GFlick Home", drives_html)
    return Response(html)


async def view_slug(req):
    file_name = unquote(req.path_params["file_name"])
    slug = db.get_or_create_link(req.path_params["file_id"])

    html = page_html(
        "View file",
        "<div>This is a <strong>publicly accessible</strong> direct link:</div>"
        f'<a href="/v/{slug}/{quote(file_name)}">{file_name}</a>',
    )
    return Response(html)


async def view_video(req):
    file_id = db.get_file_id(req.path_params["video_slug"])
    if not file_id:
        return Response("FAILED", status_code=500)

    print(f"{req.method} request headers:")
    for k, v in req.headers.items():
        print(f"  {k}: {v}")

    token = await get_token(req.app.state.httpx_client)
    if not token:
        return Response("FAILED", status_code=500)

    req_headers = {}
    req_headers["Authorization"] = f"Bearer {token}"
    if "range" in req.headers:
        req_headers["Range"] = req.headers["range"]

    url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"

    async def metadata_then_body():
        """
        First yield tuple(status_code, headers)
        Then yield chunks of response body
        """
        async with req.app.state.httpx_client.stream(
            req.method, url, headers=req_headers
        ) as vid_resp:
            yield (vid_resp.status_code, vid_resp.headers)
            async for chunk in vid_resp.aiter_raw():
                yield chunk

    video = metadata_then_body()
    status_code, headers = await video.__anext__()  # just fucking end me

    if not 200 <= status_code <= 299:  # known success codes: 200, 206
        return Response(
            f"Unexpected response status from Google: {status_code}", status_code=500
        )

    # VLC android won't allow seeking if accept-ranges isn't found (?)
    headers["Accept-Ranges"] = "bytes"

    if req.method == "HEAD":
        return Response(b"", status_code=status_code, headers=headers)

    print("Response Headers:")
    for key, val in headers.items():
        print(">", key, ":", val)

    return StreamingResponse(video, headers=headers, status_code=status_code)


async def view_drive(req):
    drive_id = req.path_params["drive_id"]
    folder_id = req.path_params.get("folder_id")

    token = await get_token(req.app.state.httpx_client)
    if not token:
        return Response("FAILED", status_code=500)

    parent = folder_id or drive_id
    api_resp = await req.app.state.httpx_client.get(
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
    return Response(html)


async def view_login_get(req):
    return Response(
        page_html(
            title="Login first!",
            body="""
        <form action="/login" method="post">
            <label for="name">Enter password:</label>
            <input type="password" name="password" id="password" required autofocus />
            <input type="submit" value="Login" />
        </form>""",
        )
    )


async def view_login_post(req):
    # Manual parsing instead of using req.form() because that would require installing
    # some python-multipart lib even if we're parsing a urlencoded form (?!)
    body = (await req.body()).decode()
    form = parse_qs(body)
    password_list = form.get("password")
    password = password_list[0] if password_list else None
    if not password or password != USER_PASSWORD:
        return Response("Invalid password", status_code=500)

    # Password is correct!
    response = RedirectResponse("/", status_code=302)
    response.set_cookie("user_token", USER_TOKEN)
    return response


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        """
        Redirect to /login if user_token cookie is not present or invalid,
        with the exception of:
            /login: otherwise, we'll end up with infinite redirects
            /v/*: we do want to expose this one publicly
        """
        if request.url.path != "/login" and not request.url.path.startswith("/v/"):
            user_token = request.cookies.get("user_token")
            if not user_token or user_token != USER_TOKEN:
                response = RedirectResponse("/login", status_code=302)
                response.delete_cookie("user_token")
                return response

        # Otherwise, business as usual
        response = await call_next(request)
        return response


debug = os.environ.get("GFLICK_DEBUG") == "1"
print("Debug mode:", debug)

app = Starlette(
    debug=debug,
    routes=[
        Route("/", view_index),
        Route("/slug/{file_id}/{file_name}", view_slug),
        Route("/v/{video_slug}/{file_name}", view_video, methods=["GET", "HEAD"]),
        Route("/d/{drive_id}", view_drive),
        Route("/d/{drive_id}/{folder_id}", view_drive),
        Route("/login", view_login_get),
        Route("/login", view_login_post, methods=["POST"]),
    ],
    middleware=[Middleware(AuthMiddleware)],
)
app.state.httpx_client = httpx.AsyncClient()
