# SEUNAS

## 🤖 JARVIS — Gemini personal assistant with GitHub access

A JARVIS-style AI assistant powered by Google Gemini. Talk or type to it, and it can
**pull repositories from GitHub**, then read the code and answer questions about it.

### What you can ask

| Say / type | What Jarvis does |
|---|---|
| "List my GitHub repos" | Lists your repositories (private ones too, with a token) |
| "Pull my Mark-XLVII repo" | Clones it if it's not on this computer, otherwise `git pull` |
| "Clone torvalds/linux" / a GitHub URL | Clones any public repo |
| "Get the dev branch of SEUNAS" | Clones or switches to that branch and pulls |
| "Update all my repos" | Pulls every repo Jarvis has downloaded |
| "What's the status of SEUNAS?" | Branch, last commit, uncommitted changes |
| "What does main.py in Mark-XLVII do?" | Pulls the repo, reads the code, explains it |
| "Open Mark-XLVII" | Opens it in VS Code (or your file manager) |

### Setup (Windows, macOS or Linux)

You need **Python 3.10+** and **git**.

```bash
git clone https://github.com/SEUNAS07/SEUNAS.git
cd SEUNAS/jarvis
pip install -r requirements.txt
cp .env.example .env        # Windows: copy .env.example .env
```

Open `.env` and set at least `GEMINI_API_KEY` (free at <https://aistudio.google.com/apikey>).
Set `GITHUB_USERNAME` so Jarvis knows whose repos "my repos" means, and `GITHUB_TOKEN`
if you want private repositories.

### Run

```bash
python jarvis.py            # type to Jarvis
```

**Voice mode** (speak and hear replies):

```bash
pip install -r requirements-voice.txt
python jarvis.py --voice
```

Say "goodbye" or type `exit` to quit.

### Notes

- Repos are downloaded to `~/JarvisRepos` (change with `JARVIS_REPOS_DIR`).
- Your GitHub token is only passed to git while a command runs; it is never saved
  into a repository's config. `.env` is git-ignored so your keys aren't committed.
- Jarvis can only read files inside the repos it has downloaded.
