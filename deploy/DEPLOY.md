# Deploying Vera to vera.sha-i.com

Step by step for hosting Vera in production on an AWS Lightsail Ubuntu
instance: MCP server + web app as systemd services behind Caddy, with
automatic HTTPS. Budget roughly 30-45 minutes the first time.

## 1. Create the Lightsail instance

1. In the [Lightsail console](https://lightsail.aws.amazon.com/), **Create instance**.
2. Platform: **Linux/Unix**. Blueprint: **OS Only -> Ubuntu 22.04 LTS**.
3. Pick an instance plan -- the smallest ($5/mo, 1 GB RAM) is enough for this app (a single-process web app + MCP server, JSON file storage, no database).
4. Name it (e.g. `vera-prod`) and click **Create instance**.
5. Wait for it to show **Running**.

## 2. Attach a static IP

A Lightsail instance's public IP changes if it's ever stopped/restarted; a static IP keeps DNS pointed at the right place.

1. Lightsail console -> **Networking** tab -> **Create static IP**.
2. Attach it to the `vera-prod` instance you just created.
3. Note the static IP address -- you'll need it for the DNS record below.

## 3. Open ports 80 and 443

1. Click into the instance -> **Networking** tab -> **IPv4 Firewall**.
2. Add rules (if not already present):
   - HTTP, TCP, port 80
   - HTTPS, TCP, port 443
3. SSH (port 22) is open by default -- leave it as is.

Caddy needs 80 open even though the site is HTTPS: it's how Let's Encrypt validates the domain before issuing the certificate (and it redirects plain HTTP to HTTPS afterward).

## 4. Point vera.sha-i.com at the instance

In whichever DNS provider hosts `sha-i.com`:

1. Add an **A record**: host `vera`, value = the static IP from step 2, TTL whatever's convenient (e.g. 300s while testing, longer once it's stable).
2. Give DNS a few minutes to propagate. Check with `dig vera.sha-i.com` or `nslookup vera.sha-i.com` from your own machine -- it should resolve to the static IP before you move on, or Caddy's certificate request in step 6 will fail.

## 5. Open the Lightsail browser terminal and clone the repo

1. Lightsail console -> click the instance -> **Connect** tab -> **Connect using SSH** (opens a browser-based terminal, no local SSH key needed).
2. Clone the repo directly into `/opt/vera` (the path the systemd units and `deploy/setup.sh` expect by default):

```bash
sudo mkdir -p /opt/vera
sudo chown ubuntu:ubuntu /opt/vera
git clone https://github.com/shalynmonet/vera-alexa.git /opt/vera
cd /opt/vera
```

(If your repo is private, clone over SSH or with a personal access token instead.)

## 6. Run setup.sh

```bash
sudo bash deploy/setup.sh
```

This installs Python, the venv, Caddy, ffmpeg (converts Family Cheer recordings to one universal format so they play back on any device -- see `vera/media_convert.py`), creates the `vera` system user, installs the systemd units, and writes a starter `/etc/vera/.env` from `.env.example` -- then **stops and tells you to edit it**, since it has no real secrets yet.

Edit the real config:

```bash
sudo nano /etc/vera/.env
```

Fill in at minimum:
- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` -- the `vera-deploy` IAM user's keys. That user needs `bedrock:InvokeModel` and `polly:SynthesizeSpeech` at minimum, plus `s3:GetObject`/`s3:PutObject`/`s3:ListBucket` on your bucket if you use one and `ses:SendEmail` if you use email nudges -- a ready-to-adapt policy JSON is at `bedrock-policy.json` in the repo root (not committed, since it names your own bucket -- fill in the placeholder and attach it to the IAM user yourself).
- `VERA_ACCESS_CODE` -- a code your family will remember (digits are fine, e.g. `4817`).
- `VERA_MCP_TOKEN` -- generate one: `openssl rand -hex 32`, paste the result in.
- `VERA_S3_BUCKET` / `VERA_SES_FROM_EMAIL` if you're using S3 storage or email nudges.

Save, then run setup again to actually start everything (it's safe to re-run -- it won't touch the `.env` you just edited):

```bash
sudo bash deploy/setup.sh
```

This also runs the demo-profile reset once immediately, so both demo profiles (`judge_demo` and `rose_demo`) have real-looking data from the start instead of waiting for the 3am timer.

## 7. Check it worked

```bash
sudo systemctl status vera-mcp vera-web caddy
curl -I https://vera.sha-i.com
```

You should get a `200 OK` (or a `303` redirect to `/login` if `VERA_ACCESS_CODE` is set) -- either way, a real HTTPS response, not a connection error. Open `https://vera.sha-i.com` in a browser and confirm the login page (or the app itself) loads with a valid certificate.

If something's wrong, check logs:

```bash
sudo journalctl -u vera-mcp -n 50 --no-pager
sudo journalctl -u vera-web -n 50 --no-pager
sudo journalctl -u caddy -n 50 --no-pager
```

## 8. Set up an AWS Budgets alert

Bedrock/Polly calls cost real money per request (rate-limited, but not free) -- a budget alert catches a runaway cost before it's a surprise.

1. [AWS Billing console](https://us-east-1.console.aws.amazon.com/billing/home) -> **Budgets** -> **Create budget**.
2. Choose **Use a template** -> **Monthly cost budget**, or **Customize** if you'd rather.
3. Set a monthly budgeted amount (e.g. $20 -- generous for this app's expected traffic).
4. Add an alert threshold (e.g. 80% of budget) and an email address to notify.
5. Create the budget.

This emails you if spend is tracking over budget; it doesn't stop anything automatically, but gives you a heads-up to check `journalctl` for runaway chat loops or investigate traffic.

## Staying up to date

```bash
cd /opt/vera && sudo bash deploy/update.sh
```

Pulls the latest `main`, reinstalls any new dependencies, installs ffmpeg if an older checkout predates it, and restarts both services (and reloads Caddy, in case the Caddyfile changed).

## What's running, and why it restarts itself

- `vera-mcp.service` -- the MCP server (`server.py`), bound to `127.0.0.1:8000`.
- `vera-web.service` -- the web app (`web/app.py`), bound to `127.0.0.1:8080`, depends on `vera-mcp`.
- `vera-demo-reset.timer` -- runs `deploy/reset_demo.py` nightly at 3am, resetting both no-code demo profiles: `judge_demo` from `demo_profile.json`, and `rose_demo` from her saved baseline (`data/demo_baselines/rose.json`, written by "Save as demo baseline" on her caregiver dashboard) or `rose_demo_profile.json` if she has no baseline yet.
- Caddy -- reverse proxies `vera.sha-i.com` to both of the above (`/mcp*` to the MCP server, everything else to the web app) and handles HTTPS automatically.

All three app units have `Restart=always` and are `systemctl enable`d, so they come back after a crash and after a reboot without anyone logging back in.
