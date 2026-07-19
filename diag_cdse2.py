"""
diag_cdse2.py -- test the SAME credentials against both Sentinel Hub realms.

Why: an OAuth client created on the commercial Sentinel Hub site is rejected by
the Copernicus Data Space token endpoint with exactly the error we are seeing
(unauthorized_client), even though the client_id looks identical in form. This
tells us which system the client actually belongs to before we recreate it.

Run:  python diag_cdse2.py
"""
import os
import sys

try:
    import requests
except ImportError:
    sys.exit("Missing 'requests'. Run:  pip install requests")

HERE = os.path.dirname(os.path.abspath(__file__))
KEYFILE = os.path.join(HERE, "cdsekey.txt")

ENDPOINTS = [
    ("Copernicus Data Space (CDSE realm)",
     "https://identity.dataspace.copernicus.eu/auth/realms/CDSE"
     "/protocol/openid-connect/token",
     "This is the one PlotLens should use. Free tier."),
    ("Commercial Sentinel Hub (main realm)",
     "https://services.sentinel-hub.com/auth/realms/main"
     "/protocol/openid-connect/token",
     "Paid service. If this one works, the client was created in the wrong "
     "place -- create a new one via dataspace.copernicus.eu instead."),
    ("Commercial Sentinel Hub (legacy oauth path)",
     "https://services.sentinel-hub.com/oauth/token",
     "Older endpoint, kept here only to identify legacy clients."),
]


def load():
    if not os.path.exists(KEYFILE):
        sys.exit(f"No cdsekey.txt in {HERE}")
    lines = [l.strip() for l in open(KEYFILE, encoding="utf-8-sig") if l.strip()]
    if len(lines) < 2:
        sys.exit("cdsekey.txt needs client_id on line 1, client_secret on line 2.")
    return lines[0], lines[1]


def main():
    cid, secret = load()
    print(f"client_id : {cid[:10]}...{cid[-4:]} ({len(cid)} chars)")
    print(f"secret    : {len(secret)} chars")
    if len(secret) != 32:
        print(f"  NOTE: Sentinel Hub secrets are conventionally 32 characters. "
              f"Yours is {len(secret)}.")
        print("  A secret one character short is the classic partial-copy symptom.")
    print()

    any_ok = False
    for name, url, note in ENDPOINTS:
        print("=" * 70)
        print(name)
        print("=" * 70)
        try:
            r = requests.post(url,
                              data={"grant_type": "client_credentials",
                                    "client_id": cid, "client_secret": secret},
                              timeout=(6, 30))
        except requests.RequestException as e:
            print(f"  NETWORK ERROR: {type(e).__name__} (retry -- your connection "
                  "has been intermittent)")
            print()
            continue

        print(f"  HTTP {r.status_code}")
        if r.status_code == 200 and "access_token" in r.text:
            print("  >>> SUCCESS. This is the realm your client belongs to.")
            print(f"  >>> {note}")
            any_ok = True
        else:
            try:
                b = r.json()
                print(f"  {b.get('error')}: {b.get('error_description')}")
            except ValueError:
                print(f"  {r.text[:160]}")
        print()

    if not any_ok:
        print("=" * 70)
        print("REJECTED EVERYWHERE -- the secret is wrong, not the endpoint.")
        print("=" * 70)
        print("Create a new OAuth client:")
        print("  1. Sign in at dataspace.copernicus.eu")
        print("  2. Hover the profile icon -> Sentinel Hub")
        print("  3. User Settings -> OAuth clients -> create new")
        print("  4. Use the COPY BUTTON for the secret. Do not select it by hand.")
        print("  5. Paste into cdsekey.txt line 2 before closing the dialog.")
        print()
        print("The secret cannot be retrieved later, so if in any doubt, make a")
        print("new client rather than trying to verify the old one.")


if __name__ == "__main__":
    main()
