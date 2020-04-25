# Boring, simple threaded server

```sh
pip install requests
echo server.py | entr -r python server.py
# http://localhost:8000/v/<gdrive_file_id>
```

# Shiny (read: weird) async server

```sh
pip install starlette aiohttp uvicorn
uvicorn asyncserver:app --reload
# http://localhost:8000/v/<gdrive_file_id>
```

# Quick run list

Mostly for my personal use. TL;DR:

- create non-root user
- create systemd service
- create nginx site with
  + letsencrypt
  + basic auth

```sh
apt install python3.7
adduser --disabled-password gflick
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
  --email caophim@imnhan.com \
  -d v.imnhan.com
# Now that we have the cert files in place, serve the full site
ln -s -f /etc/nginx/sites-available/gflick /etc/nginx/sites-enabled/gflick
systemctl restart nginx
