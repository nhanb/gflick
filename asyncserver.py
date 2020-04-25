import os

import aiohttp
from starlette.applications import Starlette
from starlette.responses import StreamingResponse
from starlette.routing import Route

CLIENT_ID = os.environ["GFLICK_ID"]
CLIENT_SECRET = os.environ["GFLICK_SECRET"]
REFRESH_TOKEN = os.environ["GFLICK_REFRESH"]
ACCESS_TOKEN = None

CHUNK_SIZE = 1024 * 1024 * 2  # 2MB in bytes

AIOHTTP_SESSION = None


async def get_access_token():
    token = None
    async with AIOHTTP_SESSION.post(
        "https://www.googleapis.com/oauth2/v4/token",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data=(
            f"client_id={CLIENT_ID}"
            f"&client_secret={CLIENT_SECRET}"
            f"&refresh_token={REFRESH_TOKEN}"
            "&grant_type=refresh_token"
        ),
    ) as resp:
        if resp.status != 200:
            print("\nGet token failed:")
            print(resp.status)
            print(await resp.text(), "\n")
        else:
            token = (await resp.json())["access_token"]
            print(f"Got new access token: {token[:15]}[...]")

    return token


async def get_video(request, file_id, is_retry=False):
    global ACCESS_TOKEN

    if ACCESS_TOKEN is None:
        print("Refreshing access token")
        ACCESS_TOKEN = await get_access_token()
    else:
        print("Using existing access token")

    req_headers = {}
    req_headers["Authorization"] = f"Bearer {ACCESS_TOKEN}"
    if "Range" in request.headers:
        req_headers["Range"] = request.headers["Range"]

    url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
    async with AIOHTTP_SESSION.get(url, headers=req_headers) as resp:
        yield resp.headers
        while True:
            chunk = await resp.content.read(CHUNK_SIZE)
            if not chunk:
                break
            yield chunk


async def video(request):
    file_id = request.path_params["file_id"]
    video = get_video(request, file_id=file_id)
    headers = await video.__anext__()  # just fucking end me

    return StreamingResponse(video, headers=headers)


async def setup_aiohttp_client():
    global AIOHTTP_SESSION
    AIOHTTP_SESSION = aiohttp.ClientSession()


async def teardown_aiohttp_client():
    global AIOHTTP_SESSION
    await AIOHTTP_SESSION.close()


app = Starlette(
    debug=True,
    routes=[Route("/v/{file_id}", video)],
    on_startup=[setup_aiohttp_client],
    on_shutdown=[teardown_aiohttp_client],
)
