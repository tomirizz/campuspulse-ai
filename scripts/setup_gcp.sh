#!/usr/bin/env bash
# Run only after the project owner has enabled billing. These actions can incur costs.
set -euo pipefail
PROJECT_ID="${1:?Usage: bash scripts/setup_gcp.sh PROJECT_ID}"
REGION="${2:-us-central1}"
gcloud services enable aiplatform.googleapis.com run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com firestore.googleapis.com storage.googleapis.com calendar-json.googleapis.com secretmanager.googleapis.com --project "$PROJECT_ID"
if ! gcloud storage buckets describe "gs://${PROJECT_ID}-agent-staging" --project "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://${PROJECT_ID}-agent-staging" --project "$PROJECT_ID" --location "$REGION" --uniform-bucket-level-access
fi
if ! gcloud firestore databases describe --database='(default)' --project "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud firestore databases create --database='(default)' --location "$REGION" --type=firestore-native --project "$PROJECT_ID"
fi
if ! gcloud iam service-accounts describe "campuspulse-web@${PROJECT_ID}.iam.gserviceaccount.com" --project "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud iam service-accounts create campuspulse-web --display-name='CampusPulse Web' --project "$PROJECT_ID"
fi
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:campuspulse-web@${PROJECT_ID}.iam.gserviceaccount.com" --role=roles/aiplatform.user --condition=None
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:campuspulse-web@${PROJECT_ID}.iam.gserviceaccount.com" --role=roles/datastore.user --condition=None
gcloud beta services identity create --service=aiplatform.googleapis.com --project "$PROJECT_ID"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com" --role=roles/aiplatform.user --condition=None
echo "Infrastructure ready. Deploy with python -m scripts.deploy_agent --project $PROJECT_ID --bucket gs://${PROJECT_ID}-agent-staging"
