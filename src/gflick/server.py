import json
import time

import curio

from .http_client import post

with open("tokens.json", "r") as tfile:
    tokens = json.load(tfile)

CLIENT_ID = tokens["client_id"]
CLIENT_SECRET = tokens["client_secret"]
REFRESH_TOKEN = tokens["refresh_token"]
ACCESS_TOKEN = None


async def echo_client(client, addr):
    print("Connection from", addr)
    while True:
        data = await client.recv(100000)
        if not data:
            break
        await client.sendall(data)
    print("Connection closed")


async def get_access_token(client_id, client_secret, refresh_token) -> str:
    print("Refreshing access token")
    start_time = time.time()

    r = await post(
        "https://www.googleapis.com/oauth2/v4/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        headers={"Accept": "application/json"},
    )

    if r.status_code != 200:
        print("\nGet token failed:")
        print(r.status_code)
        print(r.json, "\n")
        return None

    rjson = r.json
    token = rjson["access_token"]
    expiration = start_time + rjson["expires_in"]

    print(f"Got access token: {token[:15]}[...]")
    return token, expiration


def run():
    print("Started server")
    curio.run(get_access_token(CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN))
    # curio.run(curio.tcp_server, "", 25000, echo_client)
