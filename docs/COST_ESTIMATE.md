# RepoShield cost estimate and purchase priorities

Prepared 10 October 2026 for one builder, a 16 GB laptop, four people sharing expenses, and a 4–5 week deadline. Prices are checked against linked provider pages where stated. INR calculations use **₹90 per US dollar solely as a budgeting assumption**, not a live exchange-rate quote. Taxes, card conversion, region differences and renewal terms can change the actual charge. No purchase is authorized or made by this document.

## Recommendation

Build locally first. Spend nothing on cloud services in weeks one and two. Use a public synthetic GitHub demo repository. Rent hosting only after the complete local flow works, ideally for the final demonstration week. Do not buy a GPU, separate model subscription, vector database, paid UI kit or managed Kubernetes.

**Suggested shared reserve: ₹4,000–₹6,000 total, or ₹1,000–₹1,500 each.** This is a reserve, not a required spend. Expected spend can be ₹0 for a local-only submission or roughly ₹1,000–₹2,000 for a one-week hosted demonstration without a purchased domain. A full month of two-server demonstration hosting is approximately ₹4,000–₹5,000 with headroom, split ₹1,000–₹1,250 each.

## What is necessary and whether it costs money

| Item | Necessary now? | Incremental cost | Decision |
|---|---|---|---|
| Existing 16 GB laptop and internet | Yes | Already available; electricity/data excluded | Use existing hardware |
| Python, FastAPI, React, PostgreSQL, Git, local test tools | Yes where used | ₹0 service fees for local use | Pin dependencies; no managed subscriptions required |
| Linux execution environment | Yes for real isolation validation | ₹0 on existing hardware, or rented VM | Separate disposable VM; do not expose personal host files |
| Docker Desktop for education, or Linux Docker Engine | Container runtime needed | Education qualifies for free Desktop use under published terms | Recheck terms for a future company |
| GitHub account and App integration | Yes for GitHub demonstration | No separate App registration hosting line item; use free account/public demo | Hosted backend and optional usage are separate |
| Protected demo branch | Yes for enforced-gate demonstration | ₹0 on public repo with GitHub Free | Private protected repos can require a paid plan |
| Paid cloud API server | No during development | Example $12/month ≈ ₹1,080 | Optional for always-online dashboard/webhook |
| Separate rented execution server | Conditional | Example $24/month ≈ ₹2,160 | Needed if you choose remote execution instead of local VM |
| Backup and evidence copy | Yes before important remote data | ₹0 locally; small remote allowance below | Backup must be restorable, not just configured |
| Custom domain | No | Planning allowance ₹1,000–₹1,500/year | Defer; use existing/provider hostname or local demo |
| TLS certificate | Yes for public web service | Free automated certificates available | Do not buy a certificate for the MVP |
| LLM API for RepoShield | No | ₹0 mandatory | Core works without it |
| Existing coding-assistant access | Useful for development | Existing cost not included | No upgrade assumed or required by this estimate |
| Paid GitHub plan | Conditional on private-repo needs | See below | Avoid with public synthetic demo |
| Managed database/Redis | No for submission | ₹0 incremental subscription | PostgreSQL runs with trusted services; Redis deferred |
| Security review | Needed before serious commercial claims | Scope-based quote after submission | Peer review now; do not confuse that with a professional audit |

Docker documents free Desktop eligibility for education/personal use; future company eligibility must be checked separately. [Docker Desktop licensing](https://docs.docker.com/subscription-billing/desktop-license/)

Protected branches are available for public repositories on GitHub Free, and private repositories on eligible paid plans. The GitHub Team page currently lists $4/user/month; verify term and account eligibility at purchase. Four billed members would be $16/month, approximately ₹1,440 under this budget assumption. This is avoidable for the synthetic public demonstration. [Branch availability](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches), [GitHub pricing](https://github.com/pricing)

## Hosting profiles with arithmetic

Use DigitalOcean regular shared-CPU prices as a transparent reference, not a requirement to use that vendor. Published examples: 2 GiB/1 vCPU costs $12/month or $0.01786/hour; 4 GiB/2 vCPU costs $24/month or $0.03571/hour. These are low-concurrency demonstration sizes, not performance guarantees. [Droplet prices](https://www.digitalocean.com/pricing/droplets)

| Profile | Setup | Base arithmetic | Practical total to reserve | Share per person |
|---|---|---|---|---|
| A Local submission | Trusted services plus separate local Linux execution VM | No rented resources | ₹0 incremental cloud spend | ₹0 |
| B Online UI, local runner | 2 GiB trusted API/PostgreSQL host; local runner available during demo | $12 × ₹90 = ₹1,080/month | ₹1,300–₹1,800/month | ₹325–₹450 |
| C Two servers for seven days | 2 GiB trusted host and 4 GiB executor; destroy after demo | ($0.01786 + $0.03571) × 168 = $8.99976 ≈ ₹810 | ₹1,000–₹2,000 total | ₹250–₹500 |
| D Two servers for one month | Same separation, low-concurrency demo only | ($12 + $24) × ₹90 = ₹3,240 | ₹4,000–₹5,000/month | ₹1,000–₹1,250 |

Profiles C and D separate the execution machine from platform secrets; they are not approval to accept arbitrary public customer code. Provisioning, firewall validation, artifacts, restore/cleanup and credentials still need to be tested. Public multi-tenant hostile-code execution is out of the submission budget.

The 2 GiB trusted server is a starter choice for a tiny pilot/demo. Build frontend and images locally. If memory measurements show it cannot reliably run API/PostgreSQL/reverse proxy, upgrade it to 4 GiB: add $12/month ≈ ₹1,080 base, or about $3 ≈ ₹270 for one week. Do not pay for headroom before measuring.

Profile B needs the laptop online for execution. Use runner-initiated authenticated outbound polling rather than opening a home router inbound port. A stable HTTPS hostname is necessary for remote login/webhooks; use an existing/provider hostname if available. If a domain must be bought, add the separate annual allowance. A temporary tunnel may suit development, but verify current terms and stability rather than making it the final-demo dependency.

Destroy rented VMs when finished; powering them down alone may not stop all charges. Check separately for retained disks, snapshots, IPs and storage. Usage alerts are not guaranteed hard spending caps.

## Storage, backups and CI

For local development keep bounded logs on disk and an independent copy of important reports. For cloud artifacts, Cloudflare R2 Standard includes 10 GB-month storage, one million Class A and ten million Class B operations monthly; paid Standard storage is $0.015/GB-month beyond allowances, with operation charges. Budget $0–$2/month for a tiny demonstration, and enforce retention. Free allowance does not mean unlimited free requests. [R2 pricing](https://developers.cloudflare.com/r2/pricing/)

DigitalOcean's percentage-based weekly backups are 20% of the protected VM's price. For a $12 trusted server that is $2.40/month ≈ ₹216; an ephemeral runner normally needs rebuildable images rather than a backup of discarded workspaces. Also test a PostgreSQL-consistent export/restore; a VM backup alone is not a database recovery test. [Backup pricing](https://www.digitalocean.com/pricing/backups)

GitHub Free includes 2,000 Actions minutes monthly for the relevant private-repository allowance; standard hosted runners for public repositories are free under GitHub's stated conditions. Larger runners are charged separately. Linux two-core x64 overage is currently $0.006/minute, so 1,000 additional billable minutes is $6 ≈ ₹540. Keep artifacts short-lived and disable unnecessary workflow runs. [Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions), [Runner rates](https://docs.github.com/en/billing/reference/actions-runner-pricing)

Use Actions for the project's tests and demo integrations under provider policies; do not assume included minutes can be resold as unlimited hosted execution for unrelated customers.

## Optional AI expense

No LLM API is needed for analysis, decisions, authorization, sandboxing or audit. Existing coding-assistant access is separate from product operating cost. Do not assume a chat subscription includes API credit or an embeddable agent interface.

If you later choose one live model adapter, set a discretionary test cap of ₹500–₹1,000 total, shared by four. This is a user-chosen spending ceiling, not a quote for a particular model or promised number of requests. Verify the chosen provider's current rates before enabling calls; keep credentials in a trusted transport component. Defer this if the action-control milestone is incomplete.

## Four-to-five-week spending schedule

Weeks 1–2: ₹0 cloud purchases; local engine, action gateway and isolation work.

Week 3: still ₹0 if local GitHub integration can be tested with an approved development endpoint. If stable remote access is needed, choose profile B or C deliberately.

Final week: prefer profile C for a short online demonstration, or profile A if the submission is in-person and local operation is sufficient. Keep a recorded demo and local fallback.

Do not buy a year of hosting. Do not buy a domain before checking naming availability and deciding whether a custom name helps the submission. Keep four-way cost sharing distinct from GitHub paid-seat requirements.

## After submission

A customer-controlled private pilot can begin near profile B/D costs but depends on actual usage and customer hosting. Fully hosted execution should be estimated from measured jobs: sessions/runs × billed lifetime (including setup) × compute rate, plus database/storage/support. Reserve at least a separate $50–$150/month operating envelope for an exploratory small pilot if choosing hosted services; this is a planning allowance, not a production-readiness promise or mandatory purchase.

Independent review, company administration, support labor, compliance and production incident response are not included in the student infrastructure figures. Scope and quote those only after a pilot validates demand. No claim that spending ₹5,000/month makes the service enterprise-ready.
