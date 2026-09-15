#!/usr/bin/env bash
# Run the live platform E2E suite against deployed stacks.
#
#   ./e2e/run_e2e.sh                 # read-only (default, safe against prod)
#   ./e2e/run_e2e.sh --writes        # also the tests that write
#   ./e2e/run_e2e.sh --check         # just show what resolves, run nothing
#
# Read-only is the default deliberately: this suite is meant to be runnable
# against production without a second thought. --writes adds one question and
# one rating to ContextWeave and, if a team is configured, one pipeline run.
# Nothing in this suite ever deletes, and nothing sends email.
set -euo pipefail

cd "$(dirname "$0")/.."
export AWS_REGION="${AWS_REGION:-us-east-1}"

case "${1:-}" in
  --check)
    exec python3 e2e/platform_env.py --check --region "$AWS_REGION"
    ;;
  --writes)
    export WEAVE_E2E_ALLOW_WRITES=1
    echo "WRITES ENABLED — this will add a question and a rating to the live knowledge layer."
    shift
    ;;
esac

echo "region: $AWS_REGION"
python3 e2e/platform_env.py --check --region "$AWS_REGION" || {
  echo "No stack resolved. Check credentials, region, and the WEAVE_STACK_* overrides." >&2
  exit 1
}

echo
exec python3 -m pytest e2e/ -v --no-header -rs "$@"
