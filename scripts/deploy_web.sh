#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PROJECT_ID="${1:?Usage: bash scripts/deploy_web.sh PROJECT_ID ENGINE_RESOURCE_NAME}"
ENGINE_NAME="${2:?Agent Engine resource name is required}"
REGION="${3:-us-central1}"
# Private by default; use gcloud run services proxy for the demo.
gcloud run deploy campuspulse-web --source . --project "$PROJECT_ID" --region "$REGION" \
 --service-account="campuspulse-web@${PROJECT_ID}.iam.gserviceaccount.com" \
 --no-allow-unauthenticated --min-instances=0 --max-instances=2 --concurrency=4 \
 --memory=1Gi --cpu=1 --timeout=240 \
 --set-env-vars="AGENT_MODE=remote,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=${REGION},ENGINE_RESOURCE_NAME=${ENGINE_NAME},STORAGE_BACKEND=firestore,COOKIE_SECURE=true,GEMINI_MODEL=gemini-3.8-flash"
