#!/usr/bin/env python3
"""Update the Docker Hub repository overview (short description + full description/README).

Docker Hub does not auto-populate these from GitHub, so we set them via the Hub API.
Expected environment variables:
  DH_USER    Docker Hub username
  DH_TOKEN   Docker Hub token (PAT works as the login password)
  REPO_DESC  GitHub repository description (short overview)
  IMAGE_NAME image/repository name on Docker Hub (defaults to free-short-video)
"""
import os
import sys
import json
import urllib.request
import urllib.error

DOCKERHUB_API = "https://hub.docker.com/v2"


def main() -> int:
    user = os.environ["DH_USER"]
    token = os.environ["DH_TOKEN"]

    # Docker Hub caps the short `description` at 100 bytes. Exceeding it
    # rejects the ENTIRE PATCH (including full_description), so we keep this
    # concise and defensively truncate on a character boundary just in case.
    desc = "free-short-video — Self-hosted AI video generator with subtitles"
    while len(desc.encode("utf-8")) > 100:
        desc = desc[:-1]

    image = os.environ.get("IMAGE_NAME", "free-short-video")
    repo_path = f"{user}/{image}"

    # Use the repository README as the full description.
    readme = ""
    for cand in ("README.md", "readme.md", "README.MD"):
        if os.path.exists(cand):
            with open(cand, encoding="utf-8") as f:
                readme = f.read()
            break
    if not readme:
        readme = desc

    # Brand the Docker Hub overview title as "Free Short Video" without altering
    # the source README (which keeps the project name "Agnes Video Generator").
    # Only the top-level H1 line is rewritten; body mentions of "Agnes AI" stay.
    readme_lines = readme.split("\n")
    for i, line in enumerate(readme_lines):
        if line.startswith("# ") and "Agnes Video Generator" in line:
            readme_lines[i] = line.replace("Agnes Video Generator", "free-short-video", 1)
            break
    # Prepend Docker Quick Start at the very beginning of the page, after the H1.
    docker_usage = (
        "---\n\n"
        "## Quick Start (Docker)\n\n"
        "```bash\n"
        "docker run -d -p 8765:8765 \\\n"
        "  -e AGNES_API_KEY=<your-key> \\\n"
        "  -v ~/agnes-data/working:/app/.working_dir \\\n"
        "  lcy362/free-short-video:latest\n"
        "```\n\n"
        "Then open **http://localhost:8765**.\n\n"
        "---\n"
    )
    readme_lines.insert(1, docker_usage)
    readme = "\n".join(readme_lines)

    # Docker Hub caps full_description; truncate at a newline before the limit.
    limit = 24000
    if len(readme) > limit:
        cut = readme.rfind("\n", 0, limit)
        readme = (readme[:cut] if cut > 0 else readme[:limit]) + \
            "\n\n---\nFull README: https://github.com/lcy362/agnes-video-generator"

    # 1) Log in to obtain a JWT (the Hub API accepts a PAT as the password).
    try:
        req = urllib.request.Request(
            f"{DOCKERHUB_API}/users/login",
            data=json.dumps({"username": user, "password": token}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            jwt = json.load(r).get("token", "")
    except Exception as e:  # noqa: BLE001
        print("Docker Hub login failed:", e)
        return 1
    if not jwt:
        print("No JWT returned from Docker Hub")
        return 1

    # 2) Patch the repository description + full description.
    try:
        req = urllib.request.Request(
            f"{DOCKERHUB_API}/repositories/{repo_path}/",
            data=json.dumps({"description": desc, "full_description": readme}).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"JWT {jwt}"},
            method="PATCH",
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"PATCH {repo_path} -> HTTP {r.status}")
        print(f"description: {len(desc)} chars | full_description: {len(readme)} chars")
    except urllib.error.HTTPError as e:
        print("PATCH failed:", e.code, e.read().decode()[:300])
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
