import { ExternalAccountClient } from "google-auth-library";
import { getVercelOidcToken } from "@vercel/oidc";

const projectId = process.env.GCP_PROJECT_ID ?? "";
const projectNumber = process.env.GCP_PROJECT_NUMBER ?? "";
const serviceAccount = process.env.GCP_SERVICE_ACCOUNT_EMAIL ?? "";
const poolId = process.env.GCP_WORKLOAD_IDENTITY_POOL_ID ?? "";
const providerId = process.env.GCP_WORKLOAD_IDENTITY_POOL_PROVIDER_ID ?? "";
const region = process.env.GCP_REGION ?? "europe-west1";
const jobName = process.env.GCP_CLOUD_RUN_JOB ?? "prompt-analysis-worker";

export function isCloudRunConfigured() {
  return Boolean(projectId && projectNumber && serviceAccount && poolId && providerId && jobName);
}

export async function triggerCloudRunJob(jobId: string) {
  if (!isCloudRunConfigured()) throw new Error("Cloud Run n'est pas configuré.");
  const audience = `//iam.googleapis.com/projects/${projectNumber}/locations/global/workloadIdentityPools/${poolId}/providers/${providerId}`;
  const authClient = ExternalAccountClient.fromJSON({
    type: "external_account",
    audience,
    subject_token_type: "urn:ietf:params:oauth:token-type:jwt",
    token_url: "https://sts.googleapis.com/v1/token",
    service_account_impersonation_url: `https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/${serviceAccount}:generateAccessToken`,
    subject_token_supplier: { getSubjectToken: () => getVercelOidcToken() },
  });
  if (!authClient) throw new Error("Impossible d'initialiser l'identité Google Cloud.");
  const accessToken = await authClient.getAccessToken();
  if (!accessToken.token) throw new Error("Impossible d'obtenir un jeton Google Cloud.");
  const response = await fetch(`https://run.googleapis.com/v2/projects/${projectId}/locations/${region}/jobs/${jobName}:run`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken.token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ overrides: { containerOverrides: [{ args: ["--job-id", jobId] }] } }),
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`Cloud Run HTTP ${response.status}: ${(await response.text()).slice(0, 300)}`);
  const operation = await response.json();
  return { operationName: operation.name as string };
}
