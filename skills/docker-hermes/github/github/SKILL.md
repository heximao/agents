---
name: github
description: "GitHub workflows via gh CLI and REST API: auth, PRs, code review, issues, repos, CI, releases."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [GitHub, Git, gh-cli, Pull-Requests, Code-Review, Issues, Repositories, CI/CD, Authentication]
---

# GitHub Workflows

Complete guide for working with GitHub via the `gh` CLI and the REST API. Every section shows `gh` first, then a `git` + `curl` fallback for machines without `gh`. This single skill replaces the former `github-auth`, `github-pr-workflow`, `github-code-review`, `github-issues`, and `github-repo-management` skills.

**Prerequisites:** Git installed. For full API access, either `gh` CLI authenticated or a personal access token.

---

## Quick Auth Detection

Use this pattern at the start of any GitHub workflow:

```bash
# Try gh first, fall back to git + curl
if command -v gh &>/dev/null && gh auth status &>/dev/null; then
  AUTH="gh"
else
  AUTH="git"
  if [ -z "$GITHUB_TOKEN" ]; then
    if [ -f ~/.hermes/.env ] && grep -q "^GITHUB_TOKEN=" ~/.hermes/.env; then
      export GITHUB_TOKEN=$(grep "^GITHUB_TOKEN=" ~/.hermes/.env | head -1 | cut -d= -f2 | tr -d '\n\r')
    elif grep -q "github.com" ~/.git-credentials 2>/dev/null; then
      export GITHUB_TOKEN=$(grep "github.com" ~/.git-credentials | head -1 | sed 's|https://[^:]*:\([^@]*\)@.*|\1|')
    fi
  fi
fi

# Extract owner/repo from git remote
REMOTE_URL=$(git remote get-url origin 2>/dev/null)
OWNER_REPO=$(echo "$REMOTE_URL" | sed -E 's|.*github\.com[:/]||; s|\.git$||')
OWNER=$(echo "$OWNER_REPO" | cut -d/ -f1)
REPO=$(echo "$OWNER_REPO" | cut -d/ -f2)
```

A reusable script version lives at `scripts/gh-env.sh` — source it to set `$GH_AUTH_METHOD`, `$GITHUB_TOKEN`, `$GH_USER`, `$GH_OWNER`, `$GH_REPO`.

---

## 1. Authentication

### Git-Only (No gh, No sudo)

**HTTPS + Personal Access Token (recommended):**

```bash
# 1. User creates token at https://github.com/settings/tokens (scopes: repo, workflow)
# 2. Store credentials
git config --global credential.helper store
git ls-remote https://github.com/<username>/<repo>.git  # triggers credential prompt
# Username: <github-username>, Password: <token (not GitHub password)>

# 3. Set identity
git config --global user.name "Name"
git config --global user.email "email@example.com"
```

**SSH Key:**

```bash
ssh-keygen -t ed25519 -C "email@example.com" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub  # add at https://github.com/settings/keys
ssh -T git@github.com      # test
git config --global url."git@github.com:".insteadOf "https://github.com/"
```

### gh CLI

```bash
gh auth login                          # interactive browser
echo "$TOKEN" | gh auth login --with-token  # headless
gh auth setup-git                      # wire git credentials through gh
gh auth status                         # verify
```

### API Access Without gh

```bash
export GITHUB_TOKEN="<token>"
curl -s -H "Authorization: token $GITHUB_TOKEN" https://api.github.com/user
```

**Troubleshooting:** Token needs `repo` scope for push/PRs. `Permission denied` → check scopes. SSH refused on port 22 → try port 443 (`ssh.github.com`). Credentials not persisting → check `credential.helper`.

---

## 2. PR Lifecycle

### Branch → Commit → Push → Create

```bash
git checkout main && git pull origin main
git checkout -b feat/description
# (make changes with file tools)
git add src/auth.py tests/test_auth.py
git commit -m "feat(auth): add JWT authentication

- Login/register endpoints with validation
- Auth middleware for protected routes
- Unit tests for auth flow"
git push -u origin HEAD
```

**Create PR — gh:**
```bash
gh pr create --title "feat: add JWT auth" --body "## Summary\n...\n\nCloses #42" --reviewer user1 --label "enhancement"
```

**Create PR — curl:**
```bash
curl -s -X POST -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO/pulls \
  -d '{"title":"feat: add JWT auth","body":"...\n\nCloses #42","head":"'"$(git branch --show-current)"'","base":"main"}'
```

### Monitor CI

```bash
# gh
gh pr checks --watch

# curl — poll until complete
SHA=$(git rev-parse HEAD)
for i in $(seq 1 20); do
  STATUS=$(curl -s -H "Authorization: token $GITHUB_TOKEN" \
    https://api.github.com/repos/$OWNER/$REPO/commits/$SHA/status \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['state'])")
  echo "Check $i: $STATUS"
  [[ "$STATUS" =~ ^(success|failure|error)$ ]] && break
  sleep 30
done
```

### Auto-Fix CI Failures

1. Get failure logs: `gh run view <ID> --log-failed` or download via `curl .../actions/runs/<ID>/logs`
2. Diagnose (see `references/ci-troubleshooting.md` for common patterns)
3. Fix with `patch`/`write_file`, commit, push
4. Re-check CI status. Up to 3 attempts, then ask user.

### Merge

```bash
gh pr merge --squash --delete-branch           # squash + cleanup
gh pr merge --auto --squash --delete-branch    # auto-merge when checks pass
```

```bash
# curl
curl -s -X PUT -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO/pulls/$PR_NUMBER/merge \
  -d '{"merge_method":"squash","commit_title":"feat: auth (#'$PR_NUMBER')"}'
```

---

## 3. Code Review

### Local (Pre-Push) Review

```bash
git diff main...HEAD --stat          # scope
git diff main...HEAD                 # full diff
git diff main...HEAD | grep -n "print(\|console\.log\|TODO\|FIXME\|debugger"
git diff main...HEAD | grep -in "password\|secret\|api_key\|private_key"
```

Present findings as: 🔴 Critical → ⚠️ Warnings → 💡 Suggestions → ✅ Looks Good.

### PR Review

```bash
# View PR
gh pr view 123 && gh pr diff 123

# Check out locally for full review
git fetch origin pull/123/head:pr-123 && git checkout pr-123

# Post general comment
gh pr comment 123 --body "Overall looks good, minor suggestions below."

# Submit formal review
gh pr review 123 --approve --body "LGTM!"
gh pr review 123 --request-changes --body "See inline comments."
```

**Inline comments via curl (atomic multi-comment review):**
```bash
HEAD_SHA=$(curl -s -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO/pulls/123 \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['head']['sha'])")

curl -s -X POST -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO/pulls/123/reviews \
  -d '{
    "commit_id":"'"$HEAD_SHA"'",
    "event":"REQUEST_CHANGES",
    "body":"Found 2 issues. See inline.",
    "comments":[
      {"path":"src/auth.py","line":45,"body":"🔴 SQL injection — use parameterized queries."},
      {"path":"src/models.py","line":23,"body":"⚠️ Password stored without hashing."}
    ]
  }'
```

Review events: `"APPROVE"`, `"REQUEST_CHANGES"`, `"COMMENT"`. Use `references/review-output-template.md` for structured review output.

### Review Checklist

- **Correctness:** Does it work? Edge cases? Error paths?
- **Security:** No hardcoded secrets, input validation, no SQLi/XSS
- **Quality:** Clear naming, DRY, single responsibility
- **Testing:** New paths tested? Happy + error cases?
- **Performance:** No N+1 queries, no blocking in async
- **Docs:** Public APIs documented, non-obvious logic commented

---

## 4. Issues

### View / Search

```bash
gh issue list --state open --label "bug"
gh issue view 42
gh issue list --search "authentication error" --state all
```

```bash
curl -s -H "Authorization: token $GITHUB_TOKEN" \
  "https://api.github.com/repos/$OWNER/$REPO/issues?state=open&labels=bug&per_page=20" \
  | python3 -c "import sys,json; [print(f'#{i[\"number\"]}  {i[\"title\"]}') for i in json.load(sys.stdin) if 'pull_request' not in i]"
```

### Create

```bash
gh issue create --title "Login ignores ?next= param" --body "## Description\n..." --label "bug,backend" --assignee "username"
```

Templates at `templates/bug-report.md` and `templates/feature-request.md`.

### Manage

```bash
gh issue edit 42 --add-label "priority:high" --add-assignee @me
gh issue comment 42 --body "Root cause identified in auth middleware."
gh issue close 42 --reason "not planned"
gh issue reopen 42
```

### Triage Workflow

1. List untriaged: `gh issue list --label "needs-triage" --state open`
2. Read and categorize each
3. Apply labels and priority
4. Assign if owner is clear
5. Comment with triage notes

### Bulk Operations

```bash
gh issue list --label "wontfix" --json number --jq '.[].number' | \
  xargs -I {} gh issue close {} --reason "not planned"
```

---

## 5. Repository Management

### Clone / Create / Fork

```bash
gh repo clone owner/repo
gh repo create my-project --public --clone
gh repo fork owner/repo --clone
```

```bash
# curl — create repo
curl -s -X POST -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/user/repos \
  -d '{"name":"my-project","private":false,"auto_init":true,"license_template":"mit"}'

# Fork
curl -s -X POST -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/owner/repo/forks
```

### Settings & Branch Protection

```bash
gh repo edit --description "Updated" --visibility public --enable-auto-merge
```

```bash
# Branch protection via API
curl -s -X PUT -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO/branches/main/protection \
  -d '{"required_status_checks":{"strict":true,"contexts":["ci/test"]},"required_pull_request_reviews":{"required_approving_review_count":1}}'
```

### Secrets (GitHub Actions)

```bash
gh secret set API_KEY --body "value"
gh secret list
gh secret delete API_KEY
```

For curl-based secret management (requires encryption), see `references/github-api-cheatsheet.md`.

### Releases

```bash
gh release create v1.0.0 --title "v1.0.0" --generate-notes
gh release create v1.0.0 ./dist/binary --notes "Release notes"
gh release list
gh release download v1.0.0 --dir ./downloads
```

### Actions Workflows

```bash
gh workflow list
gh run list --limit 10
gh run view <RUN_ID> --log-failed
gh run rerun <RUN_ID> --failed
gh workflow run ci.yml --ref main
```

### Gists

```bash
gh gist create script.py --public --desc "Useful script"
gh gist list
```

---

## Common Pitfalls

1. **GitHub disabled password auth.** Always use a personal access token (PAT) as the password, not the GitHub account password.
2. **API returns PRs in /issues.** Filter with `"pull_request" not in item` when parsing the Issues API.
3. **Fork PR secrets unavailable.** GitHub Actions secrets are not exposed to fork PR workflows by design.
4. **`gh` not installed + no sudo.** Use the git-only + curl path — every section has a fallback.
5. **Multiple GitHub accounts.** Use SSH with different keys per host alias in `~/.ssh/config`, or per-repo credential URLs.
6. **Auto-merge requires repo setting.** The repo must have "Allow auto-merge" enabled in Settings → General.
7. **Token scopes insufficient.** `repo` for push/PRs, `workflow` for Actions, `read:org` for org repos.
8. **Inline comments need HEAD SHA.** Always fetch the PR's head commit SHA before posting review comments.
9. **Commit message format.** Use Conventional Commits: `type(scope): description`. See `references/conventional-commits.md`.

---

## Support Files

| File | Purpose |
|------|---------|
| `scripts/gh-env.sh` | Reusable auth + repo detection helper (source it) |
| `references/review-output-template.md` | Structured review comment template |
| `references/conventional-commits.md` | Commit message format reference |
| `references/ci-troubleshooting.md` | Common CI failure patterns and fixes |
| `references/github-api-cheatsheet.md` | Full REST API endpoint reference |
| `templates/bug-report.md` | Issue template for bug reports |
| `templates/feature-request.md` | Issue template for feature requests |
| `templates/pr-body-bugfix.md` | PR body template for bug fixes |
| `templates/pr-body-feature.md` | PR body template for features |
