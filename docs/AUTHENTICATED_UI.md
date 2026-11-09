# Authenticated product UI (RS2 10)

16 October update: the real demo App/installation is connected and the user
confirmed successful OAuth sign-in and repository access. Runtime configuration
is under `C:/Users/pjpra/Desktop/RepoShieldTrusted`. The local UI is
`http://127.0.0.1:8080/ui`. See [implementation status](IMPLEMENTATION_STATUS.md)
for live-check limitations; deployed HTTPS and independent multi-user review
remain unvalidated.

The PostgreSQL coordinator serves the product at `/ui`. The legacy SQLite
dashboard remains a development prototype. No React build, paid service or LLM
is required. GitHub sign-in and live required-check acceptance require operator
setup; local transport tests do not establish live GitHub acceptance.

## What the operator needs to do on GitHub

1. Use one GitHub organization for the demo, with a public repository containing
   only synthetic code/data. Give a second human reviewer organization membership
   if demonstrating independent approval. A requester cannot approve themselves.
2. Follow [GITHUB_APP.md](GITHUB_APP.md) to register/install the repository App:
   Contents read, Pull requests read, Checks write, installation on this repo only.
   Keep its RSA PEM and random webhook secret outside all execution workspaces.
   Leave webhooks inactive until a reachable HTTPS endpoint is available.
3. Separately register an **OAuth App** for browser sign-in. For local development,
   set homepage `http://127.0.0.1:8080/ui` and authorization callback
   `http://127.0.0.1:8080/ui/auth/callback`. The app requests only `read:org` to
   verify active membership. If the organization restricts OAuth applications,
   its owner must approve this application. Repository Check Runs use the separate
   installation credential, never this user token.
4. Save the OAuth client secret in an administrator-owned file outside RepoShield
   source and all registered repositories. Do not paste secrets or private keys
   into chat, commit them, or put them in an executor configuration.
5. Provide the organization login/numeric ID, public repo `owner/name`, repository
   App ID/installation ID, OAuth client ID, your GitHub numeric user ID, and local
   paths to the secret/key files. These IDs and paths are sufficient to prepare
   configuration without transmitting secret contents in messages.

GitHub documents the [authorization-code flow with state and S256 PKCE](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps)
and [authenticated organization membership](https://docs.github.com/en/rest/orgs/members#get-an-organization-membership-for-the-authenticated-user).

## Trusted configuration

Set `REPOSHIELD_UI_CONFIG_FILE` to an external administrator-owned JSON file.
Example values below are placeholders, not registered accounts or credentials:

```json
{
  "client_id": "YOUR_OAUTH_CLIENT_ID",
  "client_secret_file": "C:/RepoShieldTrusted/oauth-secret.txt",
  "origin": "http://127.0.0.1:8080",
  "allow_loopback_http": true,
  "organization": "your-demo-org",
  "organization_id": 123,
  "tenant_id": "demo",
  "members": [
    {"github_id": 456, "id": "human-admin", "role": "administrator", "repository_ids": ["shop"]},
    {"github_id": 789, "id": "human-reviewer", "role": "reviewer", "repository_ids": ["shop"]}
  ]
}
```

Use HTTPS and `allow_loopback_http: false` for anything beyond loopback development.
The origin is exact and must match the browser URL. The callback is always
`<origin>/ui/auth/callback`; arbitrary return destinations are not accepted.
The existing PostgreSQL/API identity, action-policy and signer configuration is
still required. OAuth membership does not itself grant access: the numeric GitHub
ID must also appear in this administrator-owned mapping. Roles and repository
grants are never taken from a browser form or candidate code.

Run one coordinator process. Login state and browser sessions are bounded,
short-lived and held only in that process. Restart logs everyone out; multi-process
load balancing is unsupported. Configuration changes invalidate existing browser
sessions. Organization membership is checked on each login, with a maximum
15-minute session lifetime; emergency revocation uses the local mapping or a
coordinator restart. No GitHub user token is retained after login.

Use the packaged `reposhield serve` command, which disables coordinator access
logging to avoid logging OAuth callback codes. A reverse proxy must likewise omit
query strings, cookies and authorization headers from logs, and must not expose
debug error pages. HTTPS proxy deployment and live OAuth remain acceptance work.

## Views and boundaries

Repositories show only the signed-in identity's tenant and granted repositories.
Run details show stored inputs, stages, result and audit events. Session details
show stored requests/decisions, separate approval and execution states, and audit.
Policy/settings is read-only; activation and permission changes remain trusted
operator actions. All lists are bounded and identify when older rows are omitted.

Reviewer/administrator approval calls the existing transactional service, binding
the immutable request digest and policy/snapshot context. It cannot override DENY,
approve the requester, extend expiry, or execute code on the API host. Viewer has
read-only access. Browser cookies do not authenticate the machine API. Forms
require both same-origin requests and a session-specific CSRF value.

Views omit raw process logs, credentials, private paths, reusable authorizations,
and full artifact bodies. Retained summaries are escaped and redacted; arbitrary
unrecognized secret strings in candidate text cannot be universally detected.
The UI never invents verification results or equates approval with execution.
Dedicated Linux-host validation and verification-worker/broker integration remain
pending; controlled-action observations are labeled DEVELOPMENT EXECUTION.
