# Self-hosted fallback runner `nuromix`

The CI workflow uses GitHub-hosted `ubuntu-24.04` runners first. The self-hosted runner is selected only when a trusted push to `tanyapi` or `main` does not pass one of the primary lint, test or Docker stages.

Pull-request code is never assigned to this runner.

## Required runner labels

The workflow selector is:

```yaml
runs-on: [self-hosted, linux, x64, nuromix]
```

GitHub adds `self-hosted`, `linux` and `x64` automatically for a Linux x64 runner. Add the custom label exactly as written:

```text
nuromix
```

## Host requirements

The runner host needs:

- Linux x64;
- Git;
- Python 3.12 support;
- Docker Engine and Docker Compose v2;
- enough free disk space for Docker builds;
- outbound HTTPS access to GitHub and GHCR.

Check the existing host:

```bash
git --version
python3 --version
docker --version
docker compose version
df -h /
```

## Register the runner

Open the repository in GitHub:

```text
Settings → Actions → Runners → New self-hosted runner
```

Choose Linux x64 and run the commands GitHub generates on the runner host. During configuration set the custom label:

```bash
./config.sh \
  --url https://github.com/Bambale0/banano_kling \
  --token '<ONE_TIME_TOKEN_FROM_GITHUB>' \
  --name 'nuromix' \
  --labels 'nuromix' \
  --work '_work' \
  --unattended \
  --replace
```

Use the current runner package URL and one-time token displayed by GitHub. Do not commit or paste the token into repository files.

Install it as a service from the extracted runner directory:

```bash
sudo ./svc.sh install
sudo ./svc.sh start
sudo ./svc.sh status
```

The service account must be able to run Docker. When a dedicated account is used:

```bash
sudo usermod -aG docker <runner-user>
sudo systemctl restart docker
sudo ./svc.sh stop
sudo ./svc.sh start
```

Membership in the Docker group is effectively privileged host access. Keep this runner restricted to this repository and trusted branches.

## Verify registration

In GitHub, the runner should appear as online with labels:

```text
self-hosted, linux, x64, nuromix
```

On the host:

```bash
sudo ./svc.sh status
docker ps
```

## Fallback behavior

For pushes to `tanyapi` or `main`:

1. GitHub-hosted jobs run first.
2. Their results are stored as job outputs.
3. If all primary stages pass, `nuromix fallback — Full CI validation` is skipped.
4. If any primary stage fails or does not produce a successful result, the `nuromix` runner repeats lint, regression tests, Docker build, runtime smoke checks, Compose validation and GHCR publication.
5. Production deploy waits for the final combined workflow result.

For pull requests, primary GitHub-hosted failures remain failures and no self-hosted job is scheduled.
