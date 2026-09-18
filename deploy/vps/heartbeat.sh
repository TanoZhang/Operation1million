# Sourced by daily-pass.sh. Kept separate so the exit-code contract below can
# be exercised by the test suite against the file that actually ships.
#
# The contract, in one line: the heartbeat observes the pass and never changes
# it. Whatever the pass exits with is what this script exits with.

: "${JOBDISCO_PYTHON:=/opt/jobdisco/venv/bin/python}"

heartbeat() {
  # `|| true` is the whole point: a monitor that fails the run it monitors
  # turns a good collection red and teaches the operator to ignore the alarm.
  # The module already refuses to raise; this is the second belt.
  "$JOBDISCO_PYTHON" -m jobdisco.heartbeat "$1" || true
}

heartbeat_finish() {
  # Captured first. Every command after this point overwrites $?.
  code=$?
  if [ "$code" -eq 0 ]; then
    heartbeat success
  else
    heartbeat fail
  fi
  # Restored explicitly rather than relying on bash to carry it through the
  # trap, so that a failed pass stays failed for systemd and for the operator.
  exit "$code"
}

heartbeat_arm() {
  trap heartbeat_finish EXIT
  heartbeat start
}
