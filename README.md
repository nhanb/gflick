# What

Gflick lets me play video files straight from my Google Drive without
downloading the whole thing ahead of time.
Subtitles/audio tracks and seek work out of the box.

[Demo here](https://junk.imnhan.com/gflick-phone-demo.mp4)

Motivations and design decisions are explained in my blog posts:

- [Towards an acceptable video playing experience][1]
- [Streaming videos from Google Drive - 2nd attempt][2]

After a [brief affair with async web frameworks][3], I got scared of the
ridiculous performance overhead and went back to good ol' bottle + gunicorn,
which does what I want and gets the hell out of the way.

# How?

It's basically an http proxy that does Google Drive authentication behind the
scene, exposing a plain old http endpoint that I can feed into off-the-shelf
video players.
Seeking and text/audio tracks work because the server supports [the `Range`
header](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Range).

# Development

```sh
poetry install
gflick-google
# Follow the script's instructions to authorize your newly created client.
# Once that's done, tokens.json will be created, which will be used by server.py.
gflick-dev
# Visit http://localhost:8000
```

# Running it

The `gflick` PyPI package installs a `gflick-prod` executable which can be run
as-is, as long as the current running dir has a `tokens.json` file.

There's also a `gflick-google` helper command that's supposed to be run on a
desktop which will guide you the google oauth process and spit out said
`tokens.json` file.

```sh
pip install --upgrade gflick
# assuming you've already generated a tokens.json file in current dir
gflick-prod
```

## Running it on a publicly accessible server

This is a draft mostly for my personal use, but it may give you ideas. TL;DR:

- create non-root user
- create systemd service
- create caddyfile

The whole thing can be converted into an ansible playbook (and it should be).
I'm just too lazy atm.

```sh
apt install python3  # at least 3.6
adduser --disabled-password gflick
chmod 0750 /home/gflick
su gflick
mkdir ~/gflick
cd ~/gflick
pip install --user --upgrade gflick
# [scp your tokens.json file to /home/gflick/gflick/tokens.json]

# as root:
# [populate /etc/systemd/system/gflick.service (see sample file in repo)]
systemctl enable gflick
systemctl start gflick
# Site should now be live at port 8000, but not accessible yet because ufw.
# Let's put TLS-terminating caddy server in front of it.

# [install caddy v2 - they have a debian/ubunto repo]
# Then:
mkdir /etc/caddy/sites-enabled/
cp /home/gflick/gflick/caddy/gflick.caddy /etc/caddy/sites-enabled/
# [ edit /etc/caddy/Caddyfile to simply say `import sites-enabled/*.caddy` ]
systemctl enable caddy
systemctl start caddy
```

[1]: https://hi.imnhan.com/posts/towards-an-acceptable-video-playing-experience/
[2]: https://hi.imnhan.com/posts/streaming-videos-from-google-drive-2nd-attempt/
[3]: https://github.com/nhanb/gflick/releases/tag/0.1.3
