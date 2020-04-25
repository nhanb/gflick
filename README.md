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

This is a very quick and dirty implementation that's full of duplicate code and
is built upon the standard library's non-production-ready httpserver. But hey
if you put it behind basic-auth'd nginx it's probably fine for personal use.
Maybe.

The only dependency is `requests`, which is probably available as a proper OS
package on most linux distros.

You need to first create an oauth client from console.developers.google.com,
then:

```sh
python google.py
# Follow the script's instructions to authorize your newly created client.
# Once that's done, tokens.json will be created, which will be used by server.py.
echo server.py | entr -r python server.py
# Visit http://localhost:8000
```

# Running on a publicly accessible server

This is a draft mostly for my personal use, but it may give you ideas. TL;DR:

- create non-root user
- create systemd service
- create nginx site with
  + letsencrypt
  + basic auth

The whole thing can be converted into an ansible playbook (and it should be).
I'm just too lazy atm.

```sh
apt install python3.7
adduser --disabled-password gflick
chmod 0750 /home/gflick
chown gflick:www-data /home/gflick
chown gflick:www-data /home/gflick/.htpasswd
su gflick
cd
git clone https://github.com/nhanb/gflick.git

# [write tokens.json]

# as root:
ln -s /home/gflick/gflick/systemd/gflick.service /etc/systemd/system/gflick.service
systemctl enable gflick
systemctl start gflick
# Site should now be live at port 8000, but not accessible yet because ufw.
# Let's put TLS-terminating Basic-auth'd nginx in front of it.

apt install nginx certbot
ln -s /home/gflick/gflick/nginx/gflick.conf /etc/nginx/sites-available/gflick
ln -s /home/gflick/gflick/nginx/gflick-acme-only.conf /etc/nginx/sites-available/gflick-acme-only
ln -s /home/gflick/gflick/nginx/letsencrypt.conf /etc/nginx/snippets/letsencrypt.conf

# Generate basic auth password too
apt install apache2-utils
su gflick
htpasswd -c /home/gflick/.htpasswd user1
exit # back to root

# At this point we don't have tls certs yet so the full nginx
# config won't work, therefore use a minimal config that only serves
# /.well-known/acme-challenge/ to get certs for the first time.
ln -s -f /etc/nginx/sites-available/gflick-acme-only /etc/nginx/sites-enabled/gflick
systemctl restart nginx
mkdir -p /var/www/letsencrypt
# this will create cert files in /etc/letsencrypt/ - see nginx config.
certbot certonly \
  --webroot --webroot-path /var/www/letsencrypt \
  --email gflick@imnhan.com \
  -d v.imnhan.com
# Now that we have the cert files in place, serve the full site
ln -s -f /etc/nginx/sites-available/gflick /etc/nginx/sites-enabled/gflick
systemctl restart nginx
