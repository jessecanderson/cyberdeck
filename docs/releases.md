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
   git tag -a v0.3.4 -m "Cyberdeck v0.3.4"
   git push origin v0.3.4
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

The expected result is one `release/cyberdeck-VERSION` pull request in the tap.
Its required test-bot checks validate the formula before protected `main`
auto-merges it. The cask is updated in the same commit after the formula input
has been validated. Rerunning either workflow for the same tag reuses the
existing release assets, release branch, and open pull request; it does not
open a second tap PR. To roll back, revert the tap PR through the normal
protected-branch process. To retry, fix the failed artifact or workflow input
and rerun the tagged release workflow—never move or recreate a published tag.

## macOS support

The standalone bundle and Homebrew validation run on Apple Silicon macOS 15.
Other Apple Silicon releases are best-effort until added to the release matrix;
Intel macOS is not currently packaged. Older macOS systems can encounter an
Expat dynamic-library mismatch when using the retired Homebrew-Python formula.
Use the standalone formula/cask on a supported system or the documented trusted
Python installation. Do not bypass Gatekeeper or disable platform security.
