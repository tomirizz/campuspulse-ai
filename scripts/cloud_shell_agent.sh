#!/usr/bin/env bash
# Agent Engine only. Never enables billing, grants IAM, or provisions the web/database.
set -euo pipefail
cd "$(dirname "$0")/.."

COMMAND="${1:-check}"
PROJECT_ID="${2:-campuspulse-ai-511817}"
REGION="${3:-us-central1}"
BUCKET="gs://${PROJECT_ID}-agent-staging"

if [[ "$COMMAND" == "--help" || "$COMMAND" == "help" ]]; then
  printf '%s\n' 'Usage: bash scripts/cloud_shell_agent.sh check|prepare|deploy|verify [PROJECT_ID] [REGION]' \
    'check: read-only project/account/billing checks' \
    'prepare: enable Vertex/Storage APIs, create staging bucket, install local Python dependencies' \
    'deploy: run a live Vertex Gemini check, then create/update the managed agent (billable)' \
    'verify: call the deployed API and write local evidence (billable)' \
    'No billing linkage, IAM changes, Cloud Run or Firestore provisioning is performed.'
  exit 0
fi
if [[ ! "$PROJECT_ID" =~ ^[a-z][a-z0-9-]{4,28}[a-z0-9]$ || ! "$REGION" =~ ^[a-z]+-[a-z]+[0-9]+$ ]]; then
  printf '%s\n' 'Invalid project ID or deployment region.' >&2
  exit 2
fi
case "$COMMAND" in check|prepare|deploy|verify) ;; *) printf '%s\n' 'Unknown command. Use --help.' >&2; exit 2 ;; esac

command -v gcloud >/dev/null || { printf '%s\n' 'Run this script in Google Cloud Shell.' >&2; exit 2; }
printf '%s\n' "Target project: $PROJECT_ID" "Agent region: $REGION"
gcloud auth list --filter=status:ACTIVE --format='value(account)'
gcloud projects describe "$PROJECT_ID" --format='value(projectId)'
BILLING_ENABLED="$(gcloud billing projects describe "$PROJECT_ID" --format='value(billingEnabled)')"
if [[ "${BILLING_ENABLED,,}" != "true" ]]; then
  printf '%s\n' 'STOP: project billing is not enabled. No resources were created. The owner must decide whether to link an active billing account.' >&2
  exit 3
fi
printf '%s\n' 'Billing is enabled. This is not a balance, credit or spending-limit check.'
export GOOGLE_CLOUD_PROJECT="$PROJECT_ID"
export GOOGLE_CLOUD_LOCATION="$REGION"
export GEMINI_LOCATION=global
export GEMINI_MODEL="${GEMINI_MODEL:-gemini-3.8-flash}"

case "$COMMAND" in
  check)
    printf '%s\n' 'Read-only checks passed. API/IAM/model availability still require subsequent validation.'
    ;;
  prepare)
    gcloud services enable aiplatform.googleapis.com storage.googleapis.com --project "$PROJECT_ID"
    if ! gcloud storage buckets describe "$BUCKET" --project "$PROJECT_ID" >/dev/null 2>&1; then
      gcloud storage buckets create "$BUCKET" --project "$PROJECT_ID" --location "$REGION" --uniform-bucket-level-access
    fi
    command -v uv >/dev/null || { printf '%s\n' 'uv is required; see the Cloud Shell tools/Python setup documentation.' >&2; exit 2; }
    if [[ ! -x .venv/bin/python ]]; then
      uv venv --python 3.11 .venv
    fi
    .venv/bin/python -c 'import sys; assert sys.version_info[:2] == (3, 11), "Use a separate Python 3.11 virtual environment"'
    uv pip install --python .venv/bin/python -r requirements.lock
    env GEMINI_API_KEY= .venv/bin/python -m scripts.preflight
    printf '%s\n' 'Agent prerequisites prepared. No managed agent, web service, database or OAuth client was created.'
    ;;
  deploy)
    [[ -x .venv/bin/python ]] || { printf '%s\n' 'Run prepare first.' >&2; exit 2; }
    .venv/bin/python -c 'import sys; assert sys.version_info[:2] == (3, 11), "Use Python 3.11 for this deployment"'
    env GEMINI_API_KEY= .venv/bin/python -m scripts.preflight --live
    UPDATE_ARGS=()
    if [[ -f deployment.json ]]; then
      EXISTING_ENGINE="$(.venv/bin/python -c 'import json,sys; d=json.load(open("deployment.json")); assert d["project"]==sys.argv[1] and d["region"]==sys.argv[2], "Existing deployment belongs to another project/region"; print(d["resource_name"])' "$PROJECT_ID" "$REGION")"
      UPDATE_ARGS=(--update "$EXISTING_ENGINE")
    fi
    .venv/bin/python -m scripts.deploy_agent --project "$PROJECT_ID" --bucket "$BUCKET" \
      --region "$REGION" --model "$GEMINI_MODEL" --gemini-location "$GEMINI_LOCATION" "${UPDATE_ARGS[@]}"
    ;;
  verify)
    [[ -x .venv/bin/python && -f deployment.json ]] || { printf '%s\n' 'A local deployment.json and prepared environment are required.' >&2; exit 2; }
    .venv/bin/python -c 'import json,sys; d=json.load(open("deployment.json")); assert d["project"]==sys.argv[1] and d["region"]==sys.argv[2], "Deployment belongs to another project/region"' "$PROJECT_ID" "$REGION"
    .venv/bin/python -m scripts.verify_cloud
    ;;
esac
