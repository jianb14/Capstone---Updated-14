# Repository instructions

## Git workflow

- The user's default destination for commits and pushes is `origin/main`.
  Use another destination only when the user explicitly requests it.
- Keep this checkout on `main` by default. If work is on a feature branch,
  integrate its intended changes into the latest `main` before pushing.
- Ordinary coding requests do not automatically authorize publishing changes.
  When the user requests a push, proceed without asking again for the branch.
- Before pushing, fetch `origin`, inspect the branch and diff, and run checks
  appropriate to the changes. Prefer a fast-forward when possible.
- Preserve remote commits and unrelated local files. Resolve divergence by
  integrating the remote changes and verifying the result; never force-push,
  discard changes, or rewrite shared history without explicit authorization.
- Stage only files belonging to the requested work. Do not include generated
  manuals, archives, diagrams, credentials, or model binaries unintentionally.
- Push explicitly with `git push origin refs/heads/main:refs/heads/main`.
  This checkout also pins a plain `git push` to local `main` -> `origin/main`.
- After pushing, verify the remote `main` hash matches local `main`, report the
  branch and commit, and state any failed or incomplete verification honestly.
