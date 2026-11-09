"""
GitHub tools for JARVIS: list, clone, pull, inspect and read repositories.

Settings come from environment variables (or the .env file next to jarvis.py):
  GITHUB_TOKEN      Personal access token. Needed for private repos; also
                    raises the API rate limit. Optional for public repos.
  GITHUB_USERNAME   Default owner when you only say a repo name.
  JARVIS_REPOS_DIR  Where repos are cloned (default: ~/JarvisRepos).

The token is never written into a remote URL or .git/config; it is passed to
git per-command as an HTTP header.
"""

import base64
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path

import requests

GITHUB_API  = "https://api.github.com"
GIT_TIMEOUT = 600

_REPO_RE = re.compile(
    r"^(?:https?://github\.com/|git@github\.com:|github\.com/)?"
    r"(?P<owner>[A-Za-z0-9-]+)/(?P<repo>[A-Za-z0-9._-]+?)(?:\.git)?/?$"
)
_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


# ── Config ───────────────────────────────────────────────────────────────────

def _token() -> str:
    return os.environ.get("GITHUB_TOKEN", "").strip()


def _repos_dir() -> Path:
    d = os.environ.get("JARVIS_REPOS_DIR") or str(Path.home() / "JarvisRepos")
    p = Path(os.path.expanduser(d))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _api_headers() -> dict:
    h = {"Accept": "application/vnd.github+json", "User-Agent": "jarvis-assistant"}
    if tok := _token():
        h["Authorization"] = f"Bearer {tok}"
    return h


_cached_login: str | None = None

def _default_owner() -> str:
    """Configured username, else the login that owns the token."""
    global _cached_login
    if user := os.environ.get("GITHUB_USERNAME", "").strip():
        return user
    if _cached_login:
        return _cached_login
    if _token():
        try:
            r = requests.get(f"{GITHUB_API}/user", headers=_api_headers(), timeout=15)
            if r.ok:
                _cached_login = r.json().get("login", "")
                return _cached_login
        except requests.RequestException:
            pass
    return ""


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_repo(repo: str, owner: str = "") -> tuple[str, str]:
    """Accepts 'owner/repo', a GitHub URL, or a bare repo name."""
    repo = (repo or "").strip().replace(" ", "-")
    if m := _REPO_RE.match(repo):
        return m["owner"], m["repo"]
    if _NAME_RE.match(repo):
        owner = (owner or "").strip() or _default_owner()
        if not owner:
            raise ValueError(
                f"I need an owner for '{repo}'. Say it as owner/repo, "
                f"or set GITHUB_USERNAME."
            )
        return owner, repo
    raise ValueError(f"'{repo}' doesn't look like a GitHub repository.")


def _resolve_case(owner: str, repo: str) -> tuple[str, str]:
    """Spoken names lose capitalisation; ask the API for the canonical name."""
    try:
        r = requests.get(f"{GITHUB_API}/repos/{owner}/{repo}", headers=_api_headers(), timeout=15)
        if r.ok:
            full = r.json().get("full_name", f"{owner}/{repo}")
            o, n = full.split("/", 1)
            return o, n
    except requests.RequestException:
        pass
    return owner, repo


def _git(args: list[str], cwd: Path | None = None) -> tuple[bool, str]:
    if not shutil.which("git"):
        return False, "Git is not installed on this computer."
    cmd = ["git"]
    if tok := _token():
        basic = base64.b64encode(f"x-access-token:{tok}".encode()).decode()
        cmd += ["-c", f"http.https://github.com/.extraheader=AUTHORIZATION: basic {basic}"]
    cmd += args
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           timeout=GIT_TIMEOUT, env=env)
    except subprocess.TimeoutExpired:
        return False, "Git timed out."
    out = (p.stdout + p.stderr).strip()
    if tok := _token():
        out = out.replace(tok, "***")
    return p.returncode == 0, out


def _find_local(name: str) -> Path | None:
    """Find a cloned repo folder by name (case-insensitive)."""
    base = _repos_dir()
    target = name.split("/")[-1].removesuffix(".git").lower()
    for d in base.iterdir():
        if d.is_dir() and d.name.lower() == target and (d / ".git").exists():
            return d
    return None


def _short(text: str, limit: int = 400) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[-limit:]


# ── Actions ──────────────────────────────────────────────────────────────────

def _list(owner: str, limit: int) -> str:
    owner = owner.strip()
    me = _default_owner()
    if _token() and (not owner or owner.lower() == me.lower()):
        url = f"{GITHUB_API}/user/repos"
        params = {"per_page": limit, "sort": "updated", "affiliation": "owner,collaborator"}
        who = me or "you"
    else:
        owner = owner or me
        if not owner:
            return "Tell me whose repositories to list, or set GITHUB_USERNAME."
        url = f"{GITHUB_API}/users/{owner}/repos"
        params = {"per_page": limit, "sort": "updated"}
        who = owner
    try:
        r = requests.get(url, headers=_api_headers(), params=params, timeout=20)
    except requests.RequestException as e:
        return f"Couldn't reach GitHub: {e}"
    if not r.ok:
        return f"GitHub returned {r.status_code}: {r.json().get('message', r.text)[:200]}"
    repos = r.json()
    if not repos:
        return f"No repositories found for {who}."
    local = {d.name.lower() for d in _repos_dir().iterdir() if (d / '.git').exists()}
    lines = []
    for x in repos:
        flag = " [private]" if x.get("private") else ""
        here = " (cloned)" if x["name"].lower() in local else ""
        desc = f" — {x['description']}" if x.get("description") else ""
        lines.append(f"• {x['full_name']}{flag}{here}{desc}")
    return f"{len(repos)} repositories for {who}:\n" + "\n".join(lines)


def _clone(repo: str, owner: str, branch: str) -> str:
    o, n = _resolve_case(*_parse_repo(repo, owner))
    dest = _repos_dir() / n
    if (dest / ".git").exists():
        return f"{n} is already cloned. " + _pull(n, owner, branch)
    args = ["clone", f"https://github.com/{o}/{n}.git", str(dest)]
    if branch:
        args[1:1] = ["--branch", branch]
    ok, out = _git(args)
    if not ok:
        return f"Clone of {o}/{n} failed: {_short(out)}"
    return f"Cloned {o}/{n} into {dest}."


def _pull(repo: str, owner: str, branch: str) -> str:
    local = _find_local(repo)
    if not local:
        return _clone(repo, owner, branch)
    if branch:
        ok, out = _git(["checkout", branch], cwd=local)
        if not ok:
            ok, out = _git(["checkout", "-b", branch, f"origin/{branch}"], cwd=local)
            if not ok:
                return f"Couldn't switch {local.name} to {branch}: {_short(out)}"
    ok, out = _git(["pull", "--ff-only"], cwd=local)
    if not ok:
        return f"Pull of {local.name} failed: {_short(out)}"
    if "Already up to date" in out:
        return f"{local.name} is already up to date."
    return f"Pulled latest changes into {local.name}. {_short(out, 200)}"


def _pull_all() -> str:
    repos = [d for d in sorted(_repos_dir().iterdir()) if (d / ".git").exists()]
    if not repos:
        return f"No repositories in {_repos_dir()} yet."
    results = []
    for d in repos:
        ok, out = _git(["pull", "--ff-only"], cwd=d)
        if not ok:
            results.append(f"• {d.name}: failed — {_short(out, 120)}")
        elif "Already up to date" in out:
            results.append(f"• {d.name}: up to date")
        else:
            results.append(f"• {d.name}: updated")
    return f"Pulled {len(repos)} repositories:\n" + "\n".join(results)


def _status(repo: str) -> str:
    local = _find_local(repo)
    if not local:
        return f"{repo} isn't cloned yet. Ask me to clone it first."
    _, branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=local)
    _, last   = _git(["log", "-1", "--pretty=%h %s (%cr, %an)"], cwd=local)
    _, dirty  = _git(["status", "--porcelain"], cwd=local)
    changes = len([l for l in dirty.splitlines() if l.strip()])
    state = f"{changes} uncommitted change(s)" if changes else "working tree clean"
    return f"{local.name} on branch {branch}. Last commit: {last}. {state}. Path: {local}"


def _open(repo: str) -> str:
    local = _find_local(repo)
    if not local:
        return f"{repo} isn't cloned yet."
    if code := shutil.which("code"):
        subprocess.Popen([code, str(local)])
        return f"Opened {local.name} in VS Code."
    system = platform.system()
    if system == "Windows":
        os.startfile(str(local))  # type: ignore[attr-defined]
    elif system == "Darwin":
        subprocess.Popen(["open", str(local)])
    else:
        subprocess.Popen(["xdg-open", str(local)])
    return f"Opened {local.name} folder."


# ── File reading (so Jarvis can answer questions about code) ─────────────────

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
MAX_FILE_CHARS = 60_000


def _safe_path(local: Path, rel: str) -> Path:
    target = (local / (rel or "")).resolve()
    if target != local.resolve() and local.resolve() not in target.parents:
        raise ValueError("That path is outside the repository.")
    return target


# ── Gemini tools ─────────────────────────────────────────────────────────────
# Plain, typed functions with docstrings: the Gemini SDK turns these into tool
# declarations automatically and calls them when the model asks.

def list_repos(owner: str = "", limit: int = 30) -> str:
    """List GitHub repositories. Leave owner empty for the user's own repos.

    Args:
        owner: GitHub user or organisation. Empty means the configured user.
        limit: Maximum number of repositories to return (1-100).
    """
    return _list(owner or "", max(1, min(int(limit or 30), 100)))


def pull_repo(repo: str, owner: str = "", branch: str = "") -> str:
    """Download or update a GitHub repository on this computer.
    Clones it if it is not here yet, otherwise runs git pull.

    Args:
        repo: 'owner/name', a GitHub URL, or just the name for the user's own repos.
        owner: Optional owner if repo is a bare name.
        branch: Optional branch to clone or switch to.
    """
    try:
        return _pull(repo, owner or "", branch or "")
    except ValueError as e:
        return str(e)


def pull_all_repos() -> str:
    """Run git pull on every repository already cloned on this computer."""
    return _pull_all()


def repo_status(repo: str) -> str:
    """Show branch, last commit and uncommitted changes for a cloned repository.

    Args:
        repo: Name of a repository that has been cloned.
    """
    return _status(repo)


def open_repo(repo: str) -> str:
    """Open a cloned repository in VS Code (or the file manager).

    Args:
        repo: Name of a repository that has been cloned.
    """
    return _open(repo)


def list_files(repo: str, subdir: str = "") -> str:
    """List files in a cloned repository so you can decide which to read.

    Args:
        repo: Name of a repository that has been cloned.
        subdir: Optional folder inside the repo to list.
    """
    local = _find_local(repo)
    if not local:
        return f"{repo} isn't cloned yet. Pull it first."
    try:
        root = _safe_path(local, subdir)
    except ValueError as e:
        return str(e)
    if not root.is_dir():
        return f"{subdir} is not a folder in {local.name}."
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for f in sorted(filenames):
            files.append(str((Path(dirpath) / f).relative_to(local)))
            if len(files) >= 400:
                return "\n".join(files) + "\n... (truncated at 400 files)"
    return "\n".join(files) or "(empty)"


def read_file(repo: str, path: str) -> str:
    """Read a text file from a cloned repository.

    Args:
        repo: Name of a repository that has been cloned.
        path: File path relative to the repository root.
    """
    local = _find_local(repo)
    if not local:
        return f"{repo} isn't cloned yet. Pull it first."
    try:
        f = _safe_path(local, path)
    except ValueError as e:
        return str(e)
    if not f.is_file():
        return f"No file {path} in {local.name}."
    text = f.read_text(encoding="utf-8", errors="replace")
    if len(text) > MAX_FILE_CHARS:
        text = text[:MAX_FILE_CHARS] + f"\n... (truncated, {len(text):,} chars total)"
    return text


TOOLS = [list_repos, pull_repo, pull_all_repos, repo_status, open_repo, list_files, read_file]
