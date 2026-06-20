/**
 * Compose the version string shown in the UI.
 *
 * The human-meaningful release lives in `package.json` ("version") and is bumped
 * by hand per release. CI additionally passes the build commit via the
 * `APP_BUILD_SHA` env var; when present we append the short sha as semver build
 * metadata (`0.2.0+48d9549`) so every build is uniquely identifiable even when
 * the release number itself hasn't changed. Local dev builds (no sha) just show
 * the plain version.
 */
export function formatVersion(version: string, sha?: string): string {
  const trimmed = (sha ?? '').trim()
  return trimmed ? `${version}+${trimmed.slice(0, 7)}` : version
}
