# Release procedure

Releases are published automatically from `main` after hassfest, release-tooling
tests, Ruff, unit tests, and real Home Assistant API tests pass. Pull requests and
candidate-library CI runs never publish. No PyPI upload is needed for the custom
component; publish the pinned `ac-infinity-ble` requirement separately first.

## Prepare and merge

1. Update the integration and tests. Change the library pin in
   `custom_components/ac_infinity/manifest.json` when needed, and update
   `hacs.json` if the minimum Home Assistant version changes.
2. Open a PR with a Conventional Commit title. CI validates that title because
   it should become the squash commit subject:

   | Commit | Release |
   | --- | --- |
   | `fix: ...` or `perf: ...` | Patch |
   | `feat: ...` | Minor |
   | `feat!: ...` or a `BREAKING CHANGE:` footer | Major |
   | `docs: ...`, `chore: ...`, `ci: ...`, `test: ...` | No release on their own |

3. Include user-facing upgrade instructions in the PR body for breaking changes.
   Preserve the `BREAKING CHANGE:` footer in the squash body. Raising the minimum
   supported Home Assistant version is a breaking change.
4. Review passing CI and any needed hardware checks, then **Squash and merge**.
   Keep the conventional title as the squash subject. Do not manually increment
   the integration version or create a release tag.

Python Semantic Release calculates the version from commits since the latest
release tag, updates the manifest and `CHANGELOG.md`, commits those changes, and
publishes a `vX.Y.Z` tag and GitHub release with notes. The manifest stores `X.Y.Z`
without the `v`. Release commits include `[skip ci]` to avoid a release loop.
The next release after 1.0.3 with the Home Assistant 2026.9 minimum is 2.0.0.

## HACS delivery

[HACS uses published GitHub releases](https://hacs.xyz/docs/publish/start/#versions)
to discover new versions; a tag alone is insufficient. It downloads the component
from `custom_components/ac_infinity` in the tagged repository. A separate ZIP
asset and `zip_release` configuration are unnecessary for this layout.

After merging, verify the CI release job passed and the GitHub release is
published rather than a draft. Confirm its tagged manifest matches the release
version and pins an available library. HACS will discover it on its next update
check; users then install the update and restart Home Assistant. Publication does
not immediately install anything on users' systems. `hacs.json` communicates the
minimum supported Home Assistant version.

## Workflow permissions and recovery

Only the release job receives `contents: write`; validation jobs are read-only.
The workflow uses the repository's `GITHUB_TOKEN`, with no additional secret.
Repository rules must permit its release commit and tag. If rules prevent this,
use a maintainer-approved release identity that satisfies those rules; do not
disable protections as a workaround.

Runs on `main` are serialized. An older run skips publication if `main` has moved.
To retry a failure before publication, run **CI** manually on `main` with
`library_ref` blank. This repeats validation against the published dependency.
A nonempty `library_ref` builds a candidate library and disables release creation.

If a failure pushed the version commit and tag but did not publish a GitHub
release, do not bump again or move the tag. From a clean checkout of `main` containing that tag,
install `requirements-release.txt`, authenticate `GH_TOKEN` for this repository,
and preview the recovery command before running it without `--noop`:

```shell
semantic-release --noop changelog --post-to-release-tag vX.Y.Z
semantic-release changelog --post-to-release-tag vX.Y.Z
```

Replace `vX.Y.Z` with the existing failed-release tag. This publishes its generated
release notes without creating a new version. Verify the release on GitHub and
the manifest in its source archive afterward. Fix an already published bad release
with a new conventional fix PR rather than replacing its tag.
