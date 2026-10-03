#!/usr/bin/env bash
set -u

usage() {
  printf 'Usage: %s [--allow-legacy] [project-root]\n' "$0" >&2
}

allow_legacy=0
root="."

while [ "$#" -gt 0 ]; do
  case "$1" in
    --allow-legacy)
      allow_legacy=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --*)
      printf 'Unknown option: %s\n' "$1" >&2
      usage
      exit 2
      ;;
    *)
      root="$1"
      shift
      ;;
  esac
done

tasks_dir="${root%/}/tasks"
router="$tasks_dir/README.md"
errors=()
prd_count=0
legacy_count=0

add_error() {
  errors+=("$1")
}

require_file_line() {
  local file="$1"
  local pattern="$2"
  local label="$3"
  if ! grep -Eq "$pattern" "$file"; then
    add_error "$(basename "$file"): missing required header field: $label"
  fi
}

if [ ! -d "$tasks_dir" ]; then
  add_error "tasks directory not found: $tasks_dir"
fi

if [ ! -f "$router" ]; then
  add_error "tasks/README.md router is missing"
fi

if [ -d "$tasks_dir" ]; then
  shopt -s nullglob
  for file in "$tasks_dir"/*.md; do
    base="$(basename "$file")"
    [ "$base" = "README.md" ] && continue
    prd_count=$((prd_count + 1))

    if [[ "$base" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}\ -\ prd\ [a-z0-9][a-z0-9-]*\.md$ ]]; then
      require_file_line "$file" '^Created:[[:space:]]*.+' "Created"
      require_file_line "$file" '^Last Updated:[[:space:]]*.+' "Last Updated"
      require_file_line "$file" '^Status:[[:space:]]*.+' "Status"
      require_file_line "$file" '^Feature Type:[[:space:]]*.+' "Feature Type"
      require_file_line "$file" '^Owner:[[:space:]]*.+' "Owner"
    elif [[ "$base" =~ ^(prd-|PRD-).+\.md$ ]]; then
      legacy_count=$((legacy_count + 1))
      if [ "$allow_legacy" -ne 1 ]; then
        add_error "$base: legacy PRD filename requires --allow-legacy or deliberate migration"
      fi
      require_file_line "$file" '(^Status:[[:space:]]*.+|^\*\*Status:\*\*.*)' "Status"
    else
      add_error "$base: unexpected PRD filename; use 'YYYY-MM-DD - prd feature-slug.md'"
    fi

    if [ -f "$router" ] && ! grep -Fq "$base" "$router"; then
      add_error "$base: not routed in tasks/README.md"
    fi
  done
  shopt -u nullglob
fi

if [ "$prd_count" -eq 0 ]; then
  add_error "no PRD markdown files found under tasks/"
fi

if [ "${#errors[@]}" -gt 0 ]; then
  printf 'PRD contract failed:\n' >&2
  for error in "${errors[@]}"; do
    printf '%s\n' "- $error" >&2
  done
  exit 1
fi

if [ "$allow_legacy" -eq 1 ]; then
  printf 'PRD contract OK: %d PRDs routed (%d legacy allowed).\n' "$prd_count" "$legacy_count"
else
  printf 'PRD contract OK: %d PRDs routed.\n' "$prd_count"
fi
