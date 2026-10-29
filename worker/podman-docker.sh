#!/bin/sh
# wrangler drives the Docker CLI. podman differs in three ways this wrapper papers over:
#  - it has no --provenance flag, and reads the Dockerfile from stdin (-f -) badly: drop the flag, spool stdin
#  - Cloudflare's registry wants Docker manifests, not OCI: build/push in docker format
#  - podman's local RepoDigest is not the digest the registry computes after push: answer wrangler's
#    "image inspect REGISTRY_REF --format {{ json .RepoDigests }}" with the registry's own manifest digest
set -e
# wrangler dev refers to the images it builds by short name; resolve those to localhost without a prompt
export CONTAINERS_REGISTRIES_CONF="$(dirname "$0")/registries.conf"
tmp=""; args=""; next_is_file=0; inspect_ref=""; is_inspect=0
for a in "$@"; do
  if [ "$next_is_file" = 1 ]; then
    next_is_file=0
    if [ "$a" = "-" ] || [ "$a" = "/dev/stdin" ]; then tmp=$(mktemp); cat > "$tmp"; a="$tmp"; fi
  fi
  case "$a" in
    --provenance*) continue ;;
    -f|--file) next_is_file=1 ;;
    build) args="$args build --format docker"; continue ;;
    push) args="$args push --format v2s2"; continue ;;
    inspect) is_inspect=1 ;;
    registry.cloudflare.com/*) [ "$is_inspect" = 1 ] && inspect_ref="$a" ;;
  esac
  args="$args \"$a\""
done
echo "podman $args" >> "${TMPDIR:-/tmp}/podman-docker.log"
case "$*" in
  *RepoDigests*) if [ -n "$inspect_ref" ]; then
      d=$(skopeo inspect --raw "docker://$inspect_ref" | sha256sum | cut -d' ' -f1)
      echo "[\"${inspect_ref%%:*}@sha256:$d\"]" | sed "s|${inspect_ref%%:*}@|$(echo "$inspect_ref" | sed 's/:[^:/]*$//')@|"
      exit 0
    fi ;;
esac
eval podman $args; rc=$?
[ -n "$tmp" ] && rm -f "$tmp"
exit $rc
