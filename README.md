# Flask CI/CD Demo

A small Flask service for the CI/CD assignment. It provides a home endpoint and `/health` status endpoint and has no database or external runtime services.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

The service listens on port 5000. Check `http://localhost:5000/health` for `{"status":"ok"}`.

Run tests with:

```bash
pytest -q
```

## CI/CD Deployment to AWS

The GitHub Actions workflow at `.github/workflows/deploy-ec2.yml` runs on every push to `main`. It runs pytest before building an image, pushing the commit-SHA-tagged image to ECR, and deploying it to EC2 over SSH. The deployment succeeds only after `GET /health` confirms the Flask container is responding.

### AWS prerequisites

Create an ECR repository and an Amazon Linux 2023 or Ubuntu EC2 instance. Install and enable Docker and the AWS CLI on the instance. Attach an instance profile with `AmazonEC2ContainerRegistryReadOnly` (or equivalent scoped permissions) so the instance can authenticate to ECR without AWS keys on the machine. The instance security group must allow inbound application traffic on port 5000. For this SSH workflow, allow port 22 only from the CI runner's egress IP range; GitHub-hosted runner IPs can change, so a self-hosted runner with a fixed egress IP is preferable to opening SSH broadly.

Ensure the deployment user can run Docker and AWS CLI commands. The container listens on port 5000. Set `EC2_APP_PORT` to change the host port if required.

### GitHub Actions configuration

Configure these repository variables under **Settings > Secrets and variables > Actions > Variables**:

| Variable | Description |
| --- | --- |
| `AWS_REGION` | AWS region containing ECR and EC2 |
| `ECR_REPOSITORY` | ECR repository name (not the full image URI) |
| `EC2_SSH_USER` | Linux user used to connect to EC2 |
| `EC2_APP_PORT` | Optional host port; defaults to `5000` |
| `EMAIL_FROM` | Sender email address |
| `EMAIL_TO` | Recipient email address |

Configure these repository secrets under **Settings > Secrets and variables > Actions > Secrets**:

| Secret | Description |
| --- | --- |
| `AWS_ROLE_TO_ASSUME` | IAM role ARN for GitHub OIDC; grant ECR push permissions scoped to the repository and `ecr:GetAuthorizationToken` |
| `EC2_HOST` | EC2 public DNS name or address reachable by the runner |
| `EC2_SSH_PRIVATE_KEY` | Private key for the deployment user's authorized key |
| `EC2_KNOWN_HOSTS` | Pinned `known_hosts` entry for the EC2 host; do not disable host-key checking |
| `SMTP_USERNAME` | SMTP account username |
| `SMTP_PASSWORD` | SMTP account password or app password |

The workflow uses Gmail SMTP over STARTTLS (`smtp.gmail.com:587`). Keep the SMTP username and app password in GitHub Secrets; sender and recipient addresses are repository Variables.

Configure the AWS IAM OIDC provider for `token.actions.githubusercontent.com`. Restrict the role trust policy to this GitHub repository and the `main` branch. The role needs `ecr:GetAuthorizationToken` on `*` and ECR upload/image permissions (`BatchCheckLayerAvailability`, `CompleteLayerUpload`, `InitiateLayerUpload`, `PutImage`, and `UploadLayerPart`) on the target repository. The EC2 instance role separately needs pull-only ECR access.

SSH was chosen because it can run commands directly on an existing EC2 host without setting up Systems Manager managed-instance access. The workflow uses SSH to start deployment commands on EC2; the instance role then logs into ECR and pulls the image. AWS credentials are not stored in GitHub secrets or copied to EC2. Email credentials, the SSH key, host, and assumed role ARN are stored as GitHub secrets. Systems Manager Session Manager is a stronger alternative when you want to avoid inbound SSH access.

### Manual deployment

From a machine with Docker and AWS CLI configured for the target account, verify the active AWS identity and ensure the checked-out source is the commit you intend to deploy. Build and push an image tagged with that commit:

```bash
export AWS_REGION=<aws-region>
export ECR_REPOSITORY=<ecr-repository>
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export IMAGE_TAG=$(git rev-parse HEAD)
export IMAGE_URI="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPOSITORY:$IMAGE_TAG"

aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"
docker build --tag "$IMAGE_URI" .
docker push "$IMAGE_URI"
```

The EC2 instance must have Docker and AWS CLI installed, an instance profile with ECR pull permissions, and a security group that allows SSH from your deployment machine and inbound traffic on the application port. The public key corresponding to your private key must be in the deployment user's `~/.ssh/authorized_keys`. Add the verified EC2 host key to your local `~/.ssh/known_hosts`; keep strict host-key checking enabled.

Set the connection values and run the deployment script below. Use `ec2-user` for Amazon Linux or `ubuntu` for Ubuntu. Set `EC2_APP_PORT` if you use a host port other than `5000`.

```bash
export EC2_HOST="<ec2-public-dns-or-ip>"
export EC2_SSH_USER="ec2-user"
export EC2_SSH_PRIVATE_KEY_PATH="$HOME/.ssh/flask-ec2.pem"
export EC2_APP_PORT="5000"

ssh -o BatchMode=yes -o StrictHostKeyChecking=yes \
-i "$EC2_SSH_PRIVATE_KEY_PATH" "$EC2_SSH_USER@$EC2_HOST" \
bash -s -- "$IMAGE_URI" "$AWS_REGION" "$EC2_APP_PORT" <<'REMOTE'
set -Eeuo pipefail
image_uri="$1"
aws_region="$2"
app_port="$3"
container_name="flask-practice"
registry="${image_uri%%/*}"

aws ecr get-login-password --region "$aws_region" \
| docker login --username AWS --password-stdin "$registry"
docker pull "$image_uri"
docker stop "$container_name" || true
docker rm "$container_name" || true
docker run -d --restart unless-stopped --name "$container_name" \
-p "${app_port}:5000" "$image_uri"

for attempt in {1..30}; do
if curl --fail --silent "http://127.0.0.1:${app_port}/health"; then
  exit 0
fi
sleep 2
done

docker logs "$container_name" >&2 || true
echo "Deployment health check failed" >&2
exit 1
REMOTE
```

The image tag should be the commit SHA being deployed. A non-zero SSH command result means the deployment or health check failed; inspect the container on EC2 with `docker logs flask-practice`.

---

## License

MIT License

---