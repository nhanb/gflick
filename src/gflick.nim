import
  os, httpClient, asyncdispatch, asynchttpserver, json, options,
  strutils, asyncnet, httpcore

var server = newAsyncHttpServer()


proc getAccessToken(
    clientId: string,
    clientSecret: string,
    refreshToken: string
  ): Option[string] =

  let client = newHttpClient()

  let headers = newHttpHeaders({
    "Content-Type": "application/x-www-form-urlencoded",
    "Accept": "application/json",
  })

  let body = (
    "client_id=" & clientId &
    "&client_secret=" & clientSecret &
    "&refresh_token=" & refreshToken &
    "&grant_type=refresh_token"
  )

  let resp = client.request(
    "https://www.googleapis.com/oauth2/v4/token",
    httpMethod = HttpPost,
    body = body,
    headers = headers
  )

  if not resp.status.startswith("200"):
    echo "\nGet token failed:"
    echo resp.status
    echo resp.body & "\n"
    return none(string)

  return some(parseJson(resp.body)["access_token"].getStr)


proc cb(req: Request) {.async.} =

  # First fetch access token from Google

  let
    CLIENT_ID = getEnv("GFLICK_ID")
    CLIENT_SECRET = getEnv("GFLICK_SECRET")
    REFRESH_TOKEN = getEnv("GFLICK_REFRESH")

  let tokenOpt: Option[string] = getAccessToken(CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN)
  if tokenOpt.isNone:
    await req.respond(Http400, "Failed to get access token.")
    return

  let token = tokenOpt.get()
  echo "Got token: " & token

  # Now stream file from Google to end user

  var client = newAsyncHttpClient()
  let headers = newHttpHeaders({
    "Authorization": "Bearer " & token,
  })
  if req.headers.hasKey("Range"):
    headers["Range"] = req.headers["Range"]

  let fileId = "1FeZu-LUFI6Kf3pl2AjyVUdqwgDxd0KRq"
  let url = "https://www.googleapis.com/drive/v3/files/" & fileId & "?alt=media"
  let resp = await client.request(url, httpMethod=HttpGet, headers=headers)

  await req.client.send("HTTP/1.1 200 OK\c\L")
  await req.sendHeaders(resp.headers)
  await req.client.send("\c\L\c\L")

  var i = 0
  while true:
    i += 1
    let (hasData, bodyChunk) = await resp.bodyStream.read()
    if hasData:
      await req.client.send(bodyChunk)
      echo "Sent chunk " & $i
    else:
      break

echo "Starting server at port 8080"
waitFor server.serve(Port(8080), cb)
