import { defineRailway, project, service } from "railway/iac";
// This repository manages only its own resources in the environment. Other
// repositories export their own partial name.
// See https://docs.railway.com/infrastructure-as-code#multi-repo-projects
export const partial = "nu-insights";
export default defineRailway(() => {
  const nuInsights = service("nu-insights", {
    build: { builder: "DOCKERFILE", dockerfilePath: "Dockerfile" },
    healthcheck: "/api/health",
    healthcheckTimeout: 120,
    replicas: { "us-west2": 1 },
    // ON_FAILURE is Railway's default restart policy.
    deploy: { restartPolicyMaxRetries: 3 },
    domains: [{ domain: "nuinsights.josephkelly.dev", port: 8080 }],
  });

  return project("NU Insights", {
    variables: { managed: false },
    resources: [nuInsights],
  });
});
