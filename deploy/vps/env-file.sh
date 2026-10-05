#!/usr/bin/env bash
# Read /etc/operation1million/env as data, never as a script.
#
# Both the installer and the daily pass used to `.` the file, so a value was
# shell syntax: a Gmail app password pasted as Google shows it, "abcd efgh
# ijkl mnop", ran "efgh" as a command, stopped the installer under set -e,
# and printed part of the password into its log (2026-10-05). A line here is
# NAME=value, the value taken literally to the end of the line, one pair of
# surrounding quotes removed -- what systemd's EnvironmentFile reads too.

load_env_file() {
  local file=$1 line name value
  [ -r "$file" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    line=${line%$'\r'}
    case $line in ''|'#'*) continue ;; esac
    [[ $line =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
    name=${BASH_REMATCH[1]}
    value=${BASH_REMATCH[2]}
    if [[ $value =~ ^\"(.*)\"$ ]] || [[ $value =~ ^\'(.*)\'$ ]]; then
      value=${BASH_REMATCH[1]}
    fi
    export "$name=$value"
  done < "$file"
}
