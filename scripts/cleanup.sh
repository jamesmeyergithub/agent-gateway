#!/usr/bin/env bash
# ==============================================================================
# cleanup.sh: Regional Teardown for Google Cloud Agent Gateway & Agent Platform
# ==============================================================================

set -eo pipefail

# ANSI Color Codes
BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[*] $1${NC}"; }
log_success() { echo -e "${GREEN}[✓] $1${NC}"; }
log_warning() { echo -e "${YELLOW}[!] $1${NC}"; }
log_error()   { echo -e "${RED}[✗] $1${NC}"; }
log_header()  { echo -e "\n${BOLD}${BLUE}=== $1 ===${NC}"; }

# ------------------------------------------------------------------------------
# 1. Resolve Project and Region (Prompt if not provided)
# ------------------------------------------------------------------------------
PROJECT_ID=""
REGION=""
SKIP_CONFIRM=false

GATEWAY_ID="${AGENT_GATEWAY_ID:-}"

# Parse command line flags if provided
while [[ $# -gt 0 ]]; do
  case $1 in
    -p|--project)
      PROJECT_ID="$2"
      shift 2
      ;;
    -r|--region)
      REGION="$2"
      shift 2
      ;;
    -g|--gateway-id)
      GATEWAY_ID="$2"
      shift 2
      ;;
    -y|--yes|--force)
      SKIP_CONFIRM=true
      shift
      ;;
    -h|--help)
      echo "Usage: $0 [--project <gcp-project>] [--region <gcp-region>] [--yes]"
      echo "Examples:"
      echo "  $0                                            # Interactive prompt for project & region"
      echo "  $0 --project my-project --region us-east1     # Direct execution"
      echo "  $0 my-project us-east1                        # Positional arguments"
      exit 0
      ;;
    *)
      # Allow positional arguments: project first, then region
      if [[ -z "$PROJECT_ID" ]]; then
        PROJECT_ID="$1"
        shift
      elif [[ -z "$REGION" ]]; then
        REGION="$1"
        shift
      else
        echo "Unknown argument: $1"
        exit 1
      fi
      ;;
  esac
done

echo -e "${BOLD}Google Cloud Agent Gateway Regional Teardown${NC}"
echo "------------------------------------------------------------------"

# If project was not passed, prompt user (with active gcloud project as suggestion)
if [[ -z "$PROJECT_ID" ]]; then
  SUGGESTED_PROJECT="${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}"
  if [[ -n "$SUGGESTED_PROJECT" ]]; then
    read -r -p "Enter Google Cloud Project ID [default: $SUGGESTED_PROJECT]: " INPUT_PROJECT
    PROJECT_ID="${INPUT_PROJECT:-$SUGGESTED_PROJECT}"
  else
    read -r -p "Enter Google Cloud Project ID: " PROJECT_ID
  fi
fi

if [[ -z "$PROJECT_ID" ]]; then
  echo -e "${RED}[✗] Error: Google Cloud Project ID is required.${NC}"
  exit 1
fi

# If region was not passed, prompt user
if [[ -z "$REGION" ]]; then
  DEFAULT_REGION="${GOOGLE_CLOUD_REGION:-us-east1}"
  read -r -p "Enter Google Cloud Region to clean up [default: $DEFAULT_REGION]: " INPUT_REGION
  REGION="${INPUT_REGION:-$DEFAULT_REGION}"
fi

if [[ -z "$REGION" ]]; then
  echo -e "${RED}[✗] Error: Google Cloud Region is required.${NC}"
  exit 1
fi

echo ""
echo -e "${BOLD}==================================================================${NC}"
echo -e "${BOLD}Starting Cleanup in Region: ${GREEN}${REGION}${NC} (Project: ${PROJECT_ID})"
echo -e "${BOLD}==================================================================${NC}"

if [[ "$SKIP_CONFIRM" != "true" ]]; then
  read -r -p "Are you sure you want to delete all Agent Gateway demo resources in '$REGION'? [y/N]: " CONFIRM
  if [[ ! "$CONFIRM" =~ ^[yY](es)?$ ]]; then
    echo "Cleanup cancelled by user."
    exit 0
  fi
fi

# Obtain access token and numeric project number
TOKEN=$(gcloud auth print-access-token)
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)")

# ------------------------------------------------------------------------------
# Step 1: Delete Agent (Vertex AI Reasoning Engine)
# ------------------------------------------------------------------------------
log_header "Step 1: Deleting Agent Runtime / Reasoning Engine in '$REGION'"

ENGINES_JSON=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "https://${REGION}-aiplatform.googleapis.com/v1beta1/projects/${PROJECT_NUMBER}/locations/${REGION}/reasoningEngines")

# Extract matching reasoning engines
ENGINE_NAMES=$(echo "$ENGINES_JSON" | grep -o "\"projects/${PROJECT_NUMBER}/locations/${REGION}/reasoningEngines/[0-9]*\"" | tr -d '"' || true)

if [[ -z "$ENGINE_NAMES" ]]; then
  log_info "No Reasoning Engine found in region '$REGION'."
else
  for ENGINE_NAME in $ENGINE_NAMES; do
    ENGINE_ID=$(basename "$ENGINE_NAME")
    log_info "Deleting Reasoning Engine '$ENGINE_ID' (with ?force=true to clean up child sessions)..."
    DEL_OP=$(curl -s -X DELETE \
      -H "Authorization: Bearer $TOKEN" \
      "https://${REGION}-aiplatform.googleapis.com/v1beta1/${ENGINE_NAME}?force=true" | grep -o "\"name\": *\"[^\"]*\"" | cut -d'"' -f4 || true)
    
    if [[ -n "$DEL_OP" ]]; then
      log_info "Waiting for Reasoning Engine deletion operation to complete..."
      while true; do
        OP_STATUS=$(curl -s -H "Authorization: Bearer $TOKEN" "https://${REGION}-aiplatform.googleapis.com/v1beta1/${DEL_OP}")
        if echo "$OP_STATUS" | grep -q "\"done\": true"; then
          log_success "Reasoning Engine '$ENGINE_ID' deleted."
          break
        fi
        sleep 3
      done
      
      # Ensure reasoning engine is completely released from GCP cache
      log_info "Verifying Reasoning Engine dependency release..."
      for i in {1..15}; do
        STATUS_CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" \
          "https://${REGION}-aiplatform.googleapis.com/v1beta1/${ENGINE_NAME}")
        if [[ "$STATUS_CODE" == "404" ]]; then
          break
        fi
        sleep 2
      done
    else
      log_success "Reasoning Engine deleted."
    fi
  done
fi

# ------------------------------------------------------------------------------
# Step 2: Clear Regional Policies (Protect Global Policies)
# ------------------------------------------------------------------------------
log_header "Step 2: Checking IAM Access Policies"

# Check if other regions still have active Agent Gateways
OTHER_GATEWAYS=()
for CHECK_REG in us-west1 us-east1 us-central1 europe-west1; do
  if [[ "$CHECK_REG" != "$REGION" ]]; then
    CHECK_GW="agent-gateway-${CHECK_REG}"
    [[ "$CHECK_REG" == "us-west1" ]] && CHECK_GW="agent-gateway-vpc-west1"
    GW_CHECK_URL="https://networkservices.googleapis.com/v1alpha1/projects/${PROJECT_ID}/locations/${CHECK_REG}/agentGateways/${CHECK_GW}"
    GW_EXISTS=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "$GW_CHECK_URL")
    if [[ "$GW_EXISTS" == "200" ]]; then
      OTHER_GATEWAYS+=("${CHECK_REG}/${CHECK_GW}")
    fi
  fi
done

if [[ ${#OTHER_GATEWAYS[@]} -gt 0 ]]; then
  log_warning "Active Agent Gateway(s) detected in other region(s): ${OTHER_GATEWAYS[*]}."
  log_info "Preserving global IAM Access Policy & Binding to ensure environments in other regions remain operational."
else
  BINDING_URL="https://iam.googleapis.com/v3beta/projects/${PROJECT_ID}/locations/global/policyBindings/agent-gateway-allow-binding"
  POLICY_URL="https://iam.googleapis.com/v3beta/projects/${PROJECT_ID}/locations/global/accessPolicies/agent-gateway-allow-policy"

  log_info "No active gateways in other regions. Removing global IAM Policy Binding..."
  BINDING_CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "$BINDING_URL")
  if [[ "$BINDING_CODE" == "200" ]]; then
    curl -s -X DELETE -H "Authorization: Bearer $TOKEN" "$BINDING_URL" > /dev/null
    log_success "IAM Policy Binding deleted."
  fi

  log_info "Removing global IAM Access Policy..."
  POLICY_CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "$POLICY_URL")
  if [[ "$POLICY_CODE" == "200" ]]; then
    curl -s -X DELETE -H "Authorization: Bearer $TOKEN" "$POLICY_URL" > /dev/null
    log_success "IAM Access Policy deleted."
  fi
fi

# ------------------------------------------------------------------------------
# Step 3: Delete MCP Server & Endpoints from Agent Registry
# ------------------------------------------------------------------------------
log_header "Step 3: Deleting MCP Server & Services from Agent Registry in '$REGION'"

REGISTRY_URL="https://agentregistry.googleapis.com/v1/projects/${PROJECT_ID}/locations/${REGION}/services"
SERVICES_JSON=$(curl -s -H "Authorization: Bearer $TOKEN" "$REGISTRY_URL")

SERVICE_NAMES=$(echo "$SERVICES_JSON" | grep -o "\"projects/${PROJECT_ID}/locations/${REGION}/services/[^\"]*\"" | tr -d '"' || true)

if [[ -z "$SERVICE_NAMES" ]]; then
  log_info "No services registered in Agent Registry for '$REGION'."
else
  for SVC_NAME in $SERVICE_NAMES; do
    SVC_ID=$(basename "$SVC_NAME")
    log_info "Deleting Agent Registry service '$SVC_ID'..."
    curl -s -X DELETE -H "Authorization: Bearer $TOKEN" "https://agentregistry.googleapis.com/v1/${SVC_NAME}" > /dev/null
    log_success "Deleted service '$SVC_ID'."
  done
fi

# ------------------------------------------------------------------------------
# Step 4: Delete Service Extensions (AuthzPolicy & AuthzExtension)
# ------------------------------------------------------------------------------
log_header "Step 4: Deleting Service Extensions (AuthzPolicy & AuthzExtension)"

# 4a. Delete AuthzPolicy first
AUTHZ_POL_URL="https://networksecurity.googleapis.com/v1/projects/${PROJECT_ID}/locations/${REGION}/authzPolicies/iap-dryrun-policy"
POL_CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "$AUTHZ_POL_URL")
if [[ "$POL_CODE" == "200" ]]; then
  log_info "Deleting AuthzPolicy 'iap-dryrun-policy' in '$REGION'..."
  DEL_OP=$(curl -s -X DELETE -H "Authorization: Bearer $TOKEN" "$AUTHZ_POL_URL" | grep -o "\"name\": *\"[^\"]*\"" | cut -d'"' -f4 || true)
  if [[ -n "$DEL_OP" ]]; then
    while true; do
      OP_STATUS=$(curl -s -H "Authorization: Bearer $TOKEN" "https://networksecurity.googleapis.com/v1/${DEL_OP}")
      if echo "$OP_STATUS" | grep -q "\"done\": true"; then
        log_success "AuthzPolicy deleted."
        break
      fi
      sleep 2
    done
  fi
else
  log_info "AuthzPolicy not found or already deleted."
fi

# 4b. Delete AuthzExtension second
AUTHZ_EXT_URL="https://networkservices.googleapis.com/v1alpha1/projects/${PROJECT_ID}/locations/${REGION}/authzExtensions/iap-dryrun"
EXT_CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "$AUTHZ_EXT_URL")
if [[ "$EXT_CODE" == "200" ]]; then
  log_info "Deleting AuthzExtension 'iap-dryrun' in '$REGION'..."
  DEL_OP=$(curl -s -X DELETE -H "Authorization: Bearer $TOKEN" "$AUTHZ_EXT_URL" | grep -o "\"name\": *\"[^\"]*\"" | cut -d'"' -f4 || true)
  if [[ -n "$DEL_OP" ]]; then
    while true; do
      OP_STATUS=$(curl -s -H "Authorization: Bearer $TOKEN" "https://networkservices.googleapis.com/v1alpha1/${DEL_OP}")
      if echo "$OP_STATUS" | grep -q "\"done\": true"; then
        log_success "AuthzExtension deleted."
        break
      fi
      sleep 2
    done
  fi
else
  log_info "AuthzExtension not found or already deleted."
fi

# ------------------------------------------------------------------------------
# Step 5: Delete Agent Gateway
# ------------------------------------------------------------------------------
log_header "Step 5: Deleting Agent Gateway in '$REGION'"

if [[ -z "$GATEWAY_ID" ]]; then
  # Auto-discover gateway in region if present
  DISCOVERED_GW=$(curl -s -H "Authorization: Bearer $TOKEN" \
    "https://networkservices.googleapis.com/v1alpha1/projects/${PROJECT_ID}/locations/${REGION}/agentGateways" \
    | grep -o "\"projects/${PROJECT_ID}/locations/${REGION}/agentGateways/[^\"]*\"" | head -n 1 | tr -d '"' || true)
  if [[ -n "$DISCOVERED_GW" ]]; then
    GATEWAY_ID=$(basename "$DISCOVERED_GW")
    log_info "Auto-discovered Agent Gateway: '$GATEWAY_ID'"
  else
    GATEWAY_ID="agent-gateway-${REGION}"
  fi
fi

GATEWAY_URL="https://networkservices.googleapis.com/v1alpha1/projects/${PROJECT_ID}/locations/${REGION}/agentGateways/${GATEWAY_ID}"
GW_CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "$GATEWAY_URL")

if [[ "$GW_CODE" == "200" ]]; then
  log_info "Deleting Agent Gateway '$GATEWAY_ID'..."
  # Retry loop to account for GCP releasing reasoning engine reference
  DEL_OP=""
  for attempt in {1..12}; do
    RESP=$(curl -s -X DELETE -H "Authorization: Bearer $TOKEN" "$GATEWAY_URL")
    DEL_OP=$(echo "$RESP" | grep -o "\"name\": *\"[^\"]*\"" | cut -d'"' -f4 || true)
    if [[ -n "$DEL_OP" ]]; then
      break
    fi
    if echo "$RESP" | grep -q "already being used"; then
      log_info "Waiting for Google Cloud to release gateway dependency (attempt $attempt/12)..."
      sleep 5
    else
      break
    fi
  done

  if [[ -n "$DEL_OP" ]]; then
    while true; do
      OP_STATUS=$(curl -s -H "Authorization: Bearer $TOKEN" "https://networkservices.googleapis.com/v1alpha1/${DEL_OP}")
      if echo "$OP_STATUS" | grep -q "\"done\": true"; then
        log_success "Agent Gateway '$GATEWAY_ID' deleted."
        break
      fi
      sleep 3
    done
  else
    log_warning "Could not initiate gateway deletion immediately. It may already be deleting."
  fi
else
  log_info "Agent Gateway '$GATEWAY_ID' not found or already deleted."
fi

log_header "Cleanup Complete"
log_success "All resources in region '$REGION' have been successfully cleaned up!"
