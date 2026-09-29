#!/usr/bin/env bash
# Deployment steps used by .github/workflows/deploy.yml and teardown.yml. Each subcommand is
# idempotent and reads its inputs from the environment:
#   DEPLOY_TOOL   terraform | bicep
#   TARGET_ENV    dev | prod
#   LOCATION      Azure region (default eastus2)
#   IMAGE_TAG     tag of the image built by the build job
#   ARM_* / AZURE_*  set by azure/login (OIDC) and the workflow env
#
#   deploy.sh provision   create/update infra, write rg/acr/app/url to $GITHUB_OUTPUT
#   deploy.sh push        load the image artifact and push it to this environment's ACR
#   deploy.sh import      copy the image from SOURCE_ACR (dev) into this environment's ACR (prod)
#   deploy.sh roll        point the portfolio API Container App at the new image
#   deploy.sh smoke       post-deploy checks: /healthz, /readyz, /projects
#   deploy.sh destroy     tear the environment down (teardown workflow only)
set -euo pipefail

TOOL="${DEPLOY_TOOL:-terraform}"
ENV_NAME="${TARGET_ENV:?TARGET_ENV is required}"
LOCATION="${LOCATION:-eastus2}"
STACK="infra/terraform"
IMAGE="agentic-portfolio"
OUT="${GITHUB_OUTPUT:-/dev/stdout}"

region_short() {
  case "$LOCATION" in
    eastus) echo eus ;; eastus2) echo eus2 ;; westus2) echo wus2 ;; westus3) echo wus3 ;;
    centralus) echo cus ;; swedencentral) echo sdc ;; westeurope) echo weu ;;
    northeurope) echo neu ;; uksouth) echo uks ;; *) echo "${LOCATION:0:6}" ;;
  esac
}
RG_BICEP="rg-agentic-${ENV_NAME}-$(region_short)-001"

tf_init() {
  : "${TFSTATE_RESOURCE_GROUP:?set repo/environment variable TFSTATE_RESOURCE_GROUP}"
  : "${TFSTATE_STORAGE_ACCOUNT:?set repo/environment variable TFSTATE_STORAGE_ACCOUNT}"
  terraform -chdir="$STACK" init -input=false \
    -backend-config="envs/${ENV_NAME}.backend.hcl" \
    -backend-config="resource_group_name=${TFSTATE_RESOURCE_GROUP}" \
    -backend-config="storage_account_name=${TFSTATE_STORAGE_ACCOUNT}" \
    -backend-config="container_name=${TFSTATE_CONTAINER:-tfstate}"
}

provision() {
  if [[ "$TOOL" == "terraform" ]]; then
    tf_init
    terraform -chdir="$STACK" apply -auto-approve -input=false \
      -var-file="envs/${ENV_NAME}.tfvars" -var "location=${LOCATION}"
    o() { terraform -chdir="$STACK" output -raw "$1"; }
    rg=$(o AZURE_RESOURCE_GROUP); acr=$(o AZURE_CONTAINER_REGISTRY_NAME)
    app=$(o API_APP_NAME); url=$(o API_URL)
  else
    az group create --name "$RG_BICEP" --location "$LOCATION" \
      --tags env="$ENV_NAME" owner=jagadish.meduri project=agentic-ai-portfolio cost-center=portfolio -o none
    outputs=$(az deployment group create --resource-group "$RG_BICEP" \
      --name "agentic-${ENV_NAME}-${GITHUB_RUN_ID:-local}" --template-file infra/bicep/main.bicep \
      --parameters environment="$ENV_NAME" location="$LOCATION" \
      --query properties.outputs -o json)
    j() { jq -r ".$1.value" <<<"$outputs"; }
    rg=$(j AZURE_RESOURCE_GROUP); acr=$(j AZURE_CONTAINER_REGISTRY_NAME)
    app=$(j API_APP_NAME); url=$(j API_URL)
  fi
  { echo "resource_group=$rg"; echo "acr_name=$acr"; echo "app_name=$app"; echo "app_url=$url"; } >>"$OUT"
}

push() {
  : "${ACR_NAME:?}" "${IMAGE_TAG:?}"
  az acr login --name "$ACR_NAME"
  docker load -i "images/${IMAGE}.tar"
  docker tag "${IMAGE}:${IMAGE_TAG}" "${ACR_NAME}.azurecr.io/${IMAGE}:${IMAGE_TAG}"
  docker push "${ACR_NAME}.azurecr.io/${IMAGE}:${IMAGE_TAG}"
}

import() {
  : "${ACR_NAME:?}" "${SOURCE_ACR:?}" "${IMAGE_TAG:?}"
  az acr import --name "$ACR_NAME" --source "${SOURCE_ACR}.azurecr.io/${IMAGE}:${IMAGE_TAG}" \
    --image "${IMAGE}:${IMAGE_TAG}" --force
}

roll() {
  : "${RESOURCE_GROUP:?}" "${ACR_NAME:?}" "${APP_NAME:?}" "${IMAGE_TAG:?}"
  az containerapp update -g "$RESOURCE_GROUP" -n "$APP_NAME" \
    --image "${ACR_NAME}.azurecr.io/${IMAGE}:${IMAGE_TAG}" --only-show-errors -o none
}

smoke() {
  : "${APP_URL:?}"
  for i in $(seq 1 30); do
    if curl -fsS "${APP_URL}/healthz"; then echo; break; fi
    [[ $i == 30 ]] && { echo "::error::${APP_URL}/healthz never became healthy"; exit 1; }
    sleep 10
  done
  curl -fsS "${APP_URL}/readyz"; echo
  n=$(curl -fsS "${APP_URL}/projects" | jq length)
  [[ "$n" -ge 1 ]] || { echo "::error::/projects returned no projects"; exit 1; }
  echo "catalog lists $n projects"
}

destroy() {
  if [[ "$TOOL" == "terraform" ]]; then
    tf_init
    terraform -chdir="$STACK" destroy -auto-approve -input=false \
      -var-file="envs/${ENV_NAME}.tfvars" -var "location=${LOCATION}"
  else
    az group delete --name "$RG_BICEP" --yes
  fi
}

"$@"
