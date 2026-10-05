# shellcheck shell=bash
# Sourced by every script on the box that writes to the data repository.
#
# The data repository has more than one writer: this box (the fifteen-minute
# ledger backup and the daily pass) and the user's laptop, where an assistant
# records applications under job-applications/. Each pushed to `main` without
# first taking in the other's commits, so the first refused push left the two
# sides diverged, and from then on every backup push failed, the pass stopped
# on `git pull --ff-only` and the installer on `merge --ff-only` (2026-10-03).
#
# The laptop's writer commits through the GitHub API onto the tip of main, so
# it never diverges; only this box, which commits locally and pushes later,
# can. So this box replays its unpushed commits onto what was pushed (a rebase:
# they exist nowhere else, and the laptop writes every few minutes, so merging
# would add a merge commit to nearly every backup). The writers touch different
# files; the append-only ledgers also merge line by line, so both sides
# appending to applications.ndjson keep every line. A replay that still
# conflicts is abandoned, never forced: the local commits stay, nothing is
# pushed, and the caller says so.

# Line-by-line merging for the append-only files. Kept in .git/info/attributes,
# which lives with this checkout only, so nothing has to be committed to the
# data repository for it.
data_merge_attributes() {
  local dir=$1 file
  file="$dir/.git/info/attributes"
  mkdir -p "$dir/.git/info"
  for pattern in 'operational/applications.ndjson' 'operational/listing_links.ndjson' \
                 'operational/manual_jobs.ndjson' 'operational/application_outcomes.ndjson' \
                 'job-applications/*.jsonl'; do
    grep -qxF "$pattern merge=union" "$file" 2>/dev/null || echo "$pattern merge=union" >> "$file"
  done
}

# Take in what other writers pushed. Returns 0 when HEAD contains origin/main,
# 1 when the remote cannot be read or the merge conflicts (then nothing changed).
sync_data() {
  local dir=$1
  data_merge_attributes "$dir"
  if ! git -C "$dir" fetch --quiet origin; then
    echo 'WARNING: could not fetch the data repository; nothing was merged.' >&2
    return 1
  fi
  if git -C "$dir" merge-base --is-ancestor refs/remotes/origin/main HEAD; then
    return 0
  fi
  # --autostash: the review page writes the ledger between commits, and a
  # rebase refuses a dirty tree.
  if git -C "$dir" -c user.name='operation1million-vps' -c user.email='operation1million-vps@users.noreply.github.com' \
         rebase --quiet --autostash refs/remotes/origin/main; then
    return 0
  fi
  git -C "$dir" rebase --abort 2>/dev/null || true
  echo 'WARNING: the data repository could not merge what another writer pushed.' >&2
  echo '         Local commits are kept and nothing was pushed; resolve it by hand.' >&2
  return 1
}
