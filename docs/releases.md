# Releasing Cyberdeck

Cyberdeck releases are tag-driven. After the one-time repository setup below,
pushing a version tag publishes the GitHub release and updates the protected
Homebrew tap through its normal pull-request checks.

## One-time setup

Create a fine-grained GitHub personal access token that can access
`jessecanderson/homebrew-tap` with:

- Contents: read and write
- Pull requests: read and write
- Metadata: read

Store it in both `jessecanderson/cyberdeck` and `jessecanderson/homebrew-tap`
as the Actions secret `HOMEBREW_TAP_TOKEN`. Cyberdeck uses it to send the
release dispatch. The tap uses it to create the formula PR as an external
automation identity so GitHub runs the normal pull-request workflows; PRs
created with a repository's built-in `GITHUB_TOKEN` do not trigger them.

The tap repository must have auto-merge enabled. Its `main` branch remains
protected and requires the full Homebrew test-bot matrix.

## Release checklist

1. Update `pyproject.toml`, the local fallback in `src/cyberdeck/__init__.py`,
   and `CHANGELOG.md` through a pull request.
2. Merge that pull request and update local `main`.
3. Create and push the matching annotated tag:

   ```bash
   git tag -a v0.3.0 -m "Cyberdeck v0.3.0"
   git push origin v0.3.0
   ```

The tag workflow then:

1. verifies the tag matches the package version;
2. builds and smoke-tests the wheel and source distribution;
3. publishes the GitHub release and checksums;
4. dispatches the verified source URL and SHA-256 to the tap;
5. lets the tap verify the artifact, update its formula, open a PR, run the
   Homebrew matrix, and auto-merge only after every required check passes.

If any stage fails, the workflow stops without weakening branch protection or
silently publishing a partially validated formula.
