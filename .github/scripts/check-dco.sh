#!/bin/sh
# Fail when a pull-request commit lacks a Signed-off-by trailer.
# BASE_SHA is the pull request's base commit.
set -eu

if [ -z "${BASE_SHA:-}" ]; then
  echo "BASE_SHA is required" >&2
  exit 1
fi

if ! git cat-file -e "${BASE_SHA}^{commit}" 2>/dev/null; then
  echo "base commit ${BASE_SHA} is not available; fetch the full history" >&2
  exit 1
fi

fail=0
commits=$(git rev-list --no-merges "${BASE_SHA}..HEAD")
if [ -z "$commits" ]; then
  echo "No commits to check."
  exit 0
fi

for sha in $commits; do
  body=$(git log -1 --format=%B "$sha")
  if ! printf '%s\n' "$body" | grep -Eq '^Signed-off-by: .+ <[^>]+>$'; then
    echo "Missing Signed-off-by: $(git log -1 --format='%h %an <%ae> %s' "$sha")" >&2
    fail=1
  fi
done

if [ "$fail" -ne 0 ]; then
  echo "Add the trailer with: git commit -s" >&2
  exit 1
fi

echo "All commits in ${BASE_SHA}..HEAD have Signed-off-by."
