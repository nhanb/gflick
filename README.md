# What

Gflick lets me play video files straight from my Google Drive without
downloading the whole thing ahead of time.
Subtitles/audio tracks and seek work out of the box.

- [Demo here](https://junk.imnhan.com/gflick.mp4)
- [Youtube mirror](https://youtu.be/MzHS8l6-61I)

# How?

It's basically an http proxy that does Google Drive authentication behind the
scene, exposing a plain old http endpoint that I can feed into off-the-shelf
video players.
Seeking and text/audio tracks work because the server supports [the `Range`
header](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Range).

# Running it

This originally started as a quick and dirty SimpleHTTPServer proof-of-concept
and is now in the progress of being ported to run on bottle + gunicorn for some
semblance of sanity. Maybe check back later if you want to actually use it.

The following are notes for my own use which are probably out of sync with the
codebase's reality. I'll eventually clean them up. Maybe.

You need to first create an oauth client from console.developers.google.com,
then:

```sh
poetry install
gflick-google
# Follow the script's instructions to authorize your newly created client.
# Once that's done, tokens.json will be created, which will be used by server.py.
echo server.py | entr -r gflick-dev
# Visit http://localhost:8000
```

# Running on a publicly accessible server

This is a draft mostly for my personal use, but it may give you ideas. TL;DR:

- create non-root user
- create systemd service
- create caddyfile

The whole thing can be converted into an ansible playbook (and it should be).
I'm just too lazy atm.

```sh
apt install python3.7
adduser --disabled-password gflick
chmod 0750 /home/gflick
su gflick
cd
git clone https://github.com/nhanb/gflick.git

# [write tokens.json]

# as root:
ln -s /home/gflick/gflick/systemd/gflick.service /etc/systemd/system/gflick.service
systemctl enable gflick
systemctl start gflick
# Site should now be live at port 8000, but not accessible yet because ufw.
# Let's put TLS-terminating caddy server in front of it.

# [install caddy v2 - they have a debian/ubunto repo]
# Then:
mkdir /etc/caddy/sites-enabled/
cp /home/gflick/gflick/caddy/gflick /etc/caddy/sites-enabled/gflick
# [ edit /etc/caddy/Caddyfile to simply say `import sites-enabled/*` ]
systemctl enable caddy
systemctl start caddy
