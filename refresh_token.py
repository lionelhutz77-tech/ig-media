# -*- coding: utf-8 -*-
"""
Erneuert den langlebigen Instagram-Access-Token in der Cloud (GitHub Actions).

Verlaengert den Token um weitere ~60 Tage und schreibt den neuen Wert per
GitHub CLI zurueck ins Actions-Secret IG_ACCESS_TOKEN. Dadurch bleibt der
Auto-Post dauerhaft ohne PC lauffaehig.

Benoetigt:
  IG_ACCESS_TOKEN  (aktuelles Secret)
  GH_PAT           (Personal Access Token mit Rechten zum Setzen von Secrets)
"""
import os
import subprocess
from datetime import date, timedelta

import requests

REPO = "lionelhutz77-tech/ig-media"


def main():
    token = os.environ.get("IG_ACCESS_TOKEN")
    pat = os.environ.get("GH_PAT")
    if not token:
        raise SystemExit("FEHLER: IG_ACCESS_TOKEN fehlt.")
    if not pat:
        raise SystemExit("FEHLER: GH_PAT fehlt — Secret-Erneuerung nicht moeglich.")

    r = requests.get("https://graph.instagram.com/refresh_access_token", params={
        "grant_type": "ig_refresh_token", "access_token": token}, timeout=30)
    if not r.ok:
        raise SystemExit(f"Refresh fehlgeschlagen: {r.text}")

    data = r.json()
    new_token = data["access_token"]
    days = data.get("expires_in", 0) // 86400 or 60
    expiry = date.today() + timedelta(days=days)

    # Neuen Token per stdin (nicht als CLI-Argument) ins Secret schreiben.
    env = dict(os.environ, GH_TOKEN=pat)
    subprocess.run(
        ["gh", "secret", "set", "IG_ACCESS_TOKEN", "--repo", REPO],
        input=new_token.encode("utf-8"), env=env, check=True)

    with open("token_expiry.txt", "w", encoding="utf-8") as f:
        f.write(f"{expiry}\n")
    print(f"[OK] Token verlaengert, gueltig bis {expiry}. Secret aktualisiert.")


if __name__ == "__main__":
    main()
