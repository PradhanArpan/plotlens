"""
diag_cdse.py -- work out WHY CDSE credentials are being rejected.

Checks, in order:
  1. What the file actually contains (lengths, character classes, stray
     whitespace or quotes) -- without printing the secret itself.
  2. Whether the two lines might be in the wrong order.
  3. Both orders against the live token endpoint.

Run:  python diag_cdse.py
"""
import os
import re
import string
import sys

try:
    import requests
except ImportError:
    sys.exit("Missing 'requests'. Run:  pip install requests")

HERE = os.path.dirname(os.path.abspath(__file__))
KEYFILE = os.path.join(HERE, "cdsekey.txt")
TOKEN_URL = ("https://identity.dataspace.copernicus.eu/auth/realms/CDSE"
             "/protocol/openid-connect/token")


def describe(label, s):
    """Report the shape of a credential without revealing it."""
    classes = []
    if any(c in string.ascii_lowercase for c in s):
        classes.append("lowercase")
    if any(c in string.ascii_uppercase for c in s):
        classes.append("UPPERCASE")
    if any(c in string.digits for c in s):
        classes.append("digits")
    specials = sorted({c for c in s if c not in string.ascii_letters + string.digits})
    non_ascii = [c for c in s if ord(c) > 127]

    print(f"  {label}")
    print(f"    length      : {len(s)}")
    print(f"    starts with : {s[:6]!r}")
    print(f"    ends with   : {s[-4:]!r}")
    print(f"    char types  : {', '.join(classes) if classes else 'none'}")
    print(f"    specials    : {specials if specials else 'none'}")
    if non_ascii:
        print(f"    !! NON-ASCII characters present: {non_ascii}")
        print("       This usually means smart quotes or a copy from a PDF/doc.")
    if s != s.strip():
        print("    !! has leading/trailing whitespace")
    if s.startswith(('"', "'")) or s.endswith(('"', "'")):
        print("    !! wrapped in quotes -- remove them")


def looks_like_client_id(s):
    # CDSE Sentinel Hub client ids are conventionally 'sh-' followed by a UUID.
    return s.startswith("sh-") or bool(re.fullmatch(r"[0-9a-fA-F-]{36}", s))


def try_token(cid, secret, label):
    print(f"\n  Trying {label} ...")
    try:
        r = requests.post(TOKEN_URL,
                          data={"grant_type": "client_credentials",
                                "client_id": cid, "client_secret": secret},
                          timeout=(6, 30))
    except requests.RequestException as e:
        print(f"    NETWORK ERROR: {type(e).__name__}")
        return False
    print(f"    HTTP {r.status_code}")
    if r.status_code == 200:
        print("    SUCCESS -- this order works.")
        return True
    try:
        body = r.json()
        print(f"    error: {body.get('error')} / {body.get('error_description')}")
    except ValueError:
        print(f"    body: {r.text[:200]}")
    return False


def main():
    if not os.path.exists(KEYFILE):
        sys.exit(f"No cdsekey.txt in {HERE}")

    raw = open(KEYFILE, encoding="utf-8-sig").read()
    print("=" * 70)
    print("FILE INSPECTION")
    print("=" * 70)
    print(f"  raw length  : {len(raw)} chars")
    print(f"  line count  : {len(raw.splitlines())}")

    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if len(lines) < 2:
        sys.exit(f"\nNeed 2 non-empty lines, found {len(lines)}.\n"
                 "Line 1 = client_id, line 2 = client_secret.")
    if len(lines) > 2:
        print(f"  !! {len(lines)} non-empty lines -- expected exactly 2.")
        print("     Extra lines may mean the secret wrapped onto a second line.")

    a, b = lines[0], lines[1]
    print()
    describe("line 1:", a)
    print()
    describe("line 2:", b)

    print("\n" + "=" * 70)
    print("ORDER CHECK")
    print("=" * 70)
    print(f"  line 1 looks like a client_id : {looks_like_client_id(a)}")
    print(f"  line 2 looks like a client_id : {looks_like_client_id(b)}")
    if looks_like_client_id(b) and not looks_like_client_id(a):
        print("  >> The lines appear to be SWAPPED.")

    print("\n" + "=" * 70)
    print("LIVE TOKEN TEST")
    print("=" * 70)
    if try_token(a, b, "line1=id, line2=secret"):
        return
    if try_token(b, a, "line1=secret, line2=id (swapped)"):
        print("\n>> Fix: swap the two lines in cdsekey.txt.")
        return

    print("\n" + "=" * 70)
    print("BOTH ORDERS REJECTED")
    print("=" * 70)
    print("The request format is correct (the server is answering, not erroring),")
    print("so the values themselves are wrong. The secret is shown only once when")
    print("an OAuth client is created and cannot be retrieved afterwards.")
    print()
    print("Most reliable fix: create a NEW OAuth client.")
    print("  1. dataspace.copernicus.eu -> profile icon -> Sentinel Hub")
    print("  2. User Settings -> OAuth clients -> create new")
    print("  3. When the secret appears, use the copy button rather than")
    print("     selecting the text by hand, and paste it straight into")
    print("     cdsekey.txt before closing the dialog.")


if __name__ == "__main__":
    main()
