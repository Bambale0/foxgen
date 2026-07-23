# GitHub environment and secrets for production deploy

## 1) Create the deployment environment in web UI

GitHub Actions Environments cannot be created via API and must be created manually:
- Open https://github.com/Bambale0/foxgen/settings/environments/new
- Environment name: `production`
- Save.

## 2) After creation, set required environment secrets

Run in local checkout:

```bash
gh secret set DEPLOY_HOST --env production --body "your-server-host"
gh secret set DEPLOY_KNOWN_HOSTS --env production --body "your-server-host ssh-ed25519 AAAA..."
gh secret set DEPLOY_SSH_PRIVATE_KEY --env production --body "$(cat ~/.ssh/foxgen_deploy)"
```

The SSH key value must not be shared in chat.

## 3) Set required environment variables

```bash
gh api repos/Bambale0/foxgen/environments/production/variables/AUTODEPLOY_ENABLED --method PUT \
  -H "Content-Type: application/json" --input - <<'JSON'
{"name":"AUTODEPLOY_ENABLED","value":"true"}
JSON

gh api repos/Bambale0/foxgen/environments/production/variables/DEPLOY_USER --method PUT \
  -H "Content-Type: application/json" --input - <<'JSON'
{"name":"DEPLOY_USER","value":"root"}
JSON

gh api repos/Bambale0/foxgen/environments/production/variables/DEPLOY_PORT --method PUT \
  -H "Content-Type: application/json" --input - <<'JSON'
{"name":"DEPLOY_PORT","value":"22"}
JSON

gh api repos/Bambale0/foxgen/environments/production/variables/DEPLOY_PATH --method PUT \
  -H "Content-Type: application/json" --input - <<'JSON'
{"name":"DEPLOY_PATH","value":"/root/foxgen"}
JSON

gh api repos/Bambale0/foxgen/environments/production/variables/DEPLOY_COMPOSE_FILE --method PUT \
  -H "Content-Type: application/json" --input - <<'JSON'
{"name":"DEPLOY_COMPOSE_FILE","value":"docker-compose.prod.yml"}
JSON
```

## 4) Verify

```bash
gh api repos/Bambale0/foxgen/environments/production/variables --jq '.variables[] | {name, value}'
gh secret list --env production