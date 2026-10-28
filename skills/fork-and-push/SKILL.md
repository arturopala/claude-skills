---
name: fork-and-push
description: Publish local work to the user's personal GitHub fork of the current repository - install and authenticate the gh CLI if needed, create the fork under the user's account if it does not exist yet, add it as a git remote named `fork`, commit the current changes on a new branch, and push that branch to the fork. Use when the user asks to fork the repo, add their fork as a remote, or commit and push changes to their fork (rather than to origin).
---

# Fork and push: commit current changes to a branch on the user's fork

Run the steps in order. Each one is idempotent: check first and skip anything that is already done. Stop and report if a check shows something unexpected. Don't work around it.

## Step 1 – Make sure `gh` is installed and authenticated

1. Run `command -v gh`. If `gh` is missing, install it (`brew install gh` on macOS; otherwise use the platform's package manager).
2. Run `gh auth status`. If you are not logged in, **don't** try to log in yourself, because the login is interactive. Ask the user to type `! gh auth login` in the prompt (GitHub.com, browser login), and wait until they confirm.
3. Check `gh config get git_protocol`. If the existing remotes use SSH (`git@github.com:...`) and gh uses `https`, suggest `gh config set git_protocol ssh` so new remotes match. Leave it unchanged unless the user agrees.

## Step 2 – Identify upstream and the user's account

- Upstream: parse `owner/repo` from `git remote get-url origin`. If `origin` already points at the user's own account, tell the user there is nothing to fork and ask how to proceed.
- User: `gh api user -q .login`.

## Step 3 – Create the fork if it does not exist

```sh
gh repo view <user>/<repo> --json url,isFork,parent -q '{url: .url, isFork: .isFork, parent: (.parent.owner.login + "/" + .parent.name)}'
```

- If the repo exists and `parent` is the upstream, the fork is already there, so reuse it.
- If the repo exists but is not a fork of the upstream (a different repository with the same name), stop and ask the user. Don't push to it.
- If it does not exist, create the fork without cloning and without changing remotes:

  ```sh
  gh repo fork <upstream-owner>/<repo> --clone=false --remote=false --default-branch-only
  ```

  `gh repo fork` also detects an existing fork that was renamed and reports it. Use the URL it prints.

Creating a fork is a visible action on the user's GitHub account. Doing it is fine when the user asked for it in this request. Otherwise confirm first.

## Step 4 – Add the fork as a remote

1. Run `git remote -v`. If some remote already points at the fork (in SSH or HTTPS form), reuse that remote name and don't add another one.
2. Otherwise add it, using the same protocol as `origin`:

   ```sh
   git remote add fork git@github.com:<user>/<repo>.git   # or https://github.com/<user>/<repo>.git
   git fetch fork
   ```

   If the name `fork` is already taken by an unrelated URL, pick another name (e.g. the user's login) and say so.

## Step 5 – Commit the current changes on a new branch

1. Review `git status --short` and `git diff` (plus the contents of any untracked files). Make sure nothing that looks like a secret, credential, `.env` file or large build artefact gets committed. If you're unsure about a file, ask before you add it.
2. If you're on the default branch (`main`/`master`) or a branch that tracks upstream, create a new branch first: `git switch -c <name>`. Base a short kebab-case name on the change (e.g. `add-service-docs`). If the repo uses ticket-prefixed branches and the user gave a ticket, use that form.
3. Stage the files explicitly by path (not `git add -A` with unchecked files) and commit. Match the repo's commit message style (`git log --oneline -10`), and end the message with any attribution lines the session requires.
4. If there are no working-tree changes but the current branch has commits that aren't pushed, skip the commit and push those commits. If there's nothing to commit and nothing to push, tell the user and stop.

## Step 6 – Push to the fork

```sh
git push -u <fork-remote> <branch>
```

Never force-push, and never push to `origin` as part of this skill.

## Report

Tell the user, briefly:

- whether the fork was created or already existed, with its URL
- the remote name that was added or reused
- the branch name and the commit hash and subject
- the tracking setup (`<branch>` → `<fork-remote>/<branch>`)
- next steps: `gh pr create --repo <upstream-owner>/<repo>` for a PR to upstream, or the compare link GitHub printed. Don't open a PR unless the user asks.
