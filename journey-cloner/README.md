# Journey Cloner

Creates 4 Journey Builder draft clones for one promocode match campaign:

- FollowUp
- BFR
- 2H
- AFT

## Setup on VPS

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip unzip nano
unzip journey-cloner.zip
cd journey-cloner
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
nano .env
```

Paste a fresh `AUTH_TOKEN` in `.env`.

## Add templates

Put Chrome DevTools `Copy as fetch` text files here:

```text
raw_fetches/followup.txt
raw_fetches/bfr.txt
raw_fetches/two_hours.txt
raw_fetches/aft.txt
```

Then extract JSON bodies:

```bash
python extract_templates.py raw_fetches/followup.txt templates/followup.json
python extract_templates.py raw_fetches/bfr.txt templates/bfr.json
python extract_templates.py raw_fetches/two_hours.txt templates/two_hours.json
python extract_templates.py raw_fetches/aft.txt templates/aft.json
```

## Test one draft only

```bash
python create_journeys.py \
  --match "Colo Colo vs Audax" \
  --code TEST1 \
  --date 2026-06-10 \
  --time 15:00 \
  --types aft \
  --dry-run
```

Dry runs do not call the API and do not need a token. Remove `--dry-run` to
reserve an ID and create the draft.

## Create all 4 drafts

```bash
python create_journeys.py \
  --match "Colo Colo vs Audax" \
  --code TEST1 \
  --date 2026-06-10 \
  --time 15:00
```

The script will ask you to type `YES` before creating.

## Browser UI

You can also run a small local HTML form:

```bash
.venv/bin/python web_ui.py --host 127.0.0.1 --port 8088
```

Open it through an SSH tunnel:

```bash
ssh -L 8088:127.0.0.1:8088 root@YOUR_VPS_IP
```

Then open:

```text
http://127.0.0.1:8088
```

The form asks for:

- Bearer token
- Home club
- Away club
- Match date
- Match time in Chile
- Promocode
- Draft types

Keep "Dry run only" checked first. Dry runs do not call the API and do not need
a token. When creating real drafts, the UI passes the token as an environment
variable for that run and does not write it into `.env`.

## Security

Do not hardcode or share tokens. Tokens copied from DevTools expire and should be refreshed often. If you posted a token publicly or into chat, log out/revoke the session.
