"""Pull official Helm charts from ghcr.io OCI registry and save as .tgz files."""
import json
import ssl
import urllib.request
import urllib.parse
import os
import sys

DEST = os.path.join(os.path.dirname(__file__), "official-charts")
os.makedirs(DEST, exist_ok=True)

# Skip SSL verification (Windows Schannel CRL check fails in this env)
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

REGISTRY = "ghcr.io"

CHARTS = [
    {
        "repo":    "llm-d/charts/llm-d-router-standalone-dev",
        "tag":     "v0",
        "outfile": "llm-d-router-standalone-dev-v0.tgz",
    },
    {
        "repo":    "llm-d/charts/llm-d-router-gateway-dev",
        "tag":     "v0",
        "outfile": "llm-d-router-gateway-dev-v0.tgz",
    },
]


def get_token(repo: str) -> str:
    url = (
        f"https://{REGISTRY}/token"
        f"?service={REGISTRY}"
        f"&scope=repository:{repo}:pull"
    )
    with urllib.request.urlopen(url, context=ctx) as r:
        return json.loads(r.read())["token"]


def get_manifest(repo: str, tag: str, token: str) -> dict:
    url = f"https://{REGISTRY}/v2/{repo}/manifests/{tag}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": (
            "application/vnd.cncf.helm.config.v1+json,"
            "application/vnd.oci.image.manifest.v1+json,"
            "application/vnd.oci.image.index.v1+json,"
            "application/vnd.docker.distribution.manifest.v2+json"
        ),
    })
    with urllib.request.urlopen(req, context=ctx) as r:
        return json.loads(r.read())


def download_blob(repo: str, digest: str, token: str) -> bytes:
    url = f"https://{REGISTRY}/v2/{repo}/blobs/{digest}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
    })
    with urllib.request.urlopen(req, context=ctx) as r:
        return r.read()


for chart in CHARTS:
    repo    = chart["repo"]
    tag     = chart["tag"]
    outfile = os.path.join(DEST, chart["outfile"])

    print(f"\n{'='*60}")
    print(f"Pulling: {REGISTRY}/{repo}:{tag}")

    token = get_token(repo)
    print(f"  Token: {token[:30]}...")

    manifest = get_manifest(repo, tag, token)
    media_type = manifest.get("mediaType", "unknown")
    print(f"  Manifest mediaType: {media_type}")

    # Handle OCI index (multi-arch) — pick the first manifest entry
    if manifest.get("manifests"):
        print(f"  Index with {len(manifest['manifests'])} entries — fetching first child manifest")
        child_digest = manifest["manifests"][0]["digest"]
        manifest = get_manifest(repo, child_digest, token)
        media_type = manifest.get("mediaType", "unknown")
        print(f"  Child manifest mediaType: {media_type}")

    # Find the Helm chart layer
    # Helm OCI: mediaType = application/vnd.cncf.helm.chart.content.v1.tar+gzip
    layers = manifest.get("layers", [])
    print(f"  Layers ({len(layers)}):")
    for layer in layers:
        print(f"    {layer.get('mediaType')}  size={layer.get('size')}  digest={layer['digest'][:30]}...")

    helm_layer = next(
        (l for l in layers if "helm.chart.content" in l.get("mediaType", "")),
        layers[0] if layers else None,
    )

    if not helm_layer:
        print(f"  ERROR: no chart layer found in manifest")
        sys.exit(1)

    print(f"\n  Downloading chart layer ({helm_layer['size']} bytes)...")
    data = download_blob(repo, helm_layer["digest"], token)

    with open(outfile, "wb") as f:
        f.write(data)
    print(f"  Saved: {outfile}  ({len(data):,} bytes)")

print(f"\n\nAll charts saved to: {DEST}/")
for chart in CHARTS:
    path = os.path.join(DEST, chart["outfile"])
    if os.path.exists(path):
        print(f"  OK  {chart['outfile']}  ({os.path.getsize(path):,} bytes)")
    else:
        print(f"  MISSING  {chart['outfile']}")
