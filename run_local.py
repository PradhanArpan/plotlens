"""
run_local.py -- run the PlotLens pipeline locally with all credentials loaded.

Solves a recurring nuisance: `set VAR=...` in cmd only lasts for that ONE
window. Open a new terminal and every source silently falls back to synthetic,
which looks like a bug but isn't.

This reads the key files you already have (all gitignored) and sets the
environment variables in-process, so nothing needs retyping and no new file
containing secrets is created.

Expects, next to this script:
    otkey.txt    -- OpenTopography API key            (1 line)
    aqkey.txt    -- OpenAQ API key                    (1 line)
    cdsekey.txt  -- CDSE client_id / client_secret    (2 lines)

Any that are missing are simply skipped; that source stays synthetic and the
capability report will say so.

Run from the project root:   python run_local.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(HERE, "backend", "plotlens")


def read_lines(filename):
    path = os.path.join(HERE, filename)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig") as f:
        return [re.sub(r"\s+", "", ln) for ln in f if ln.strip()]


def load_credentials():
    loaded, missing = [], []

    ot = read_lines("otkey.txt")
    if ot:
        os.environ["OPENTOPOGRAPHY_API_KEY"] = ot[0]
        loaded.append("OPENTOPOGRAPHY_API_KEY")
    else:
        missing.append("otkey.txt")

    aq = read_lines("aqkey.txt")
    if aq:
        os.environ["OPENAQ_API_KEY"] = aq[0]
        loaded.append("OPENAQ_API_KEY")
    else:
        missing.append("aqkey.txt")

    cd = read_lines("cdsekey.txt")
    if len(cd) >= 2:
        os.environ["CDSE_CLIENT_ID"] = cd[0]
        os.environ["CDSE_CLIENT_SECRET"] = cd[1]
        loaded.append("CDSE_CLIENT_ID + CDSE_CLIENT_SECRET")
    elif cd:
        missing.append("cdsekey.txt (needs 2 lines, found 1)")
    else:
        missing.append("cdsekey.txt")

    print("Credentials loaded:")
    for n in loaded:
        print(f"  OK      {n}")
    for n in missing:
        print(f"  missing {n}  -> that source will stay synthetic")
    print()
    return loaded


def main():
    if not os.path.isdir(PKG):
        sys.exit(f"Cannot find the package folder: {PKG}\n"
                 "Run this from the project root (C:\\Users\\HP\\plotlens-project).")
    load_credentials()
    sys.path.insert(0, PKG)

    from plotlens.pipeline import capability_report
    import json
    print("Capability report (what can run live):")
    print(json.dumps(capability_report(), indent=2))
    print()

    # Delegate to the pipeline's own demo runner so output stays identical to
    # `python -m plotlens.pipeline`.
    import runpy
    runpy.run_module("plotlens.pipeline", run_name="__main__")


if __name__ == "__main__":
    main()
