import json
from urllib.parse import urlparse

import curio
import h11
from curio import socket


class HttpResponse:
    slots = ("status_code", "json")

    def __init__(self, status_code, json):
        self.status_code = status_code
        self.json = json


class HttpClient:
    slots = ("sock", "conn")

    @classmethod
    async def init(cls, host, port):
        """
        Use this instead of default constructor
        """
        self = cls()

        self.sock = await curio.open_connection(
            host, port, ssl=True, server_hostname=host
        )
        self.conn = h11.Connection(our_role=h11.CLIENT)
        return self

    async def send(self, *events):
        for event in events:
            data = self.conn.send(event)
            if data is None:
                # event was a ConnectionClosed(), meaning that we won't be
                # sending any more data:
                await self.sock.shutdown(socket.SHUT_WR)
            else:
                await self.sock.sendall(data)

    async def next_event(self, max_bytes_per_recv=4096):
        while True:
            # If we already have a complete event buffered internally, just
            # return that. Otherwise, read some data, add it to the internal
            # buffer, and then try again.
            event = self.conn.next_event()
            if event is h11.NEED_DATA:
                self.conn.receive_data(await self.sock.recv(max_bytes_per_recv))
                continue
            return event


async def post(url: str, data: dict, headers: dict) -> HttpResponse:
    """
    HTTPS-only dict-in-dict-out API, used for Google's non-streaming JSON auth APIs
    """
    url = urlparse(url)
    assert url.scheme == "https", url
    data = json.dumps(data).encode()

    headers["host"] = url.hostname
    headers["content-length"] = str(len(data))

    async with curio.timeout_after(20):

        client = await HttpClient.init(url.hostname, url.port or 443)
        await client.send(
            h11.Request(method="POST", target=url.path, headers=list(headers.items())),
            h11.Data(data=data),
            h11.EndOfMessage(),
        )

        resp = await client.next_event()
        body = b""
        while True:
            event = await client.next_event()
            if type(event) is h11.EndOfMessage:
                break
            body += event.data

        return HttpResponse(resp.status_code, json.loads(body))
