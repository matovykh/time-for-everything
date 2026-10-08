# Security policy

This project handles children's activity data. The MVP is not yet independently audited for public deployment.

## Reporting

Do not publish credentials, personal records or a working exploit against a live installation in an issue. Before public release, the maintainer must configure a private vulnerability-reporting channel in the repository settings. Until then, report privately to the installation owner.

## Deployment requirements

- Terminate HTTPS at a trusted reverse proxy. Use secure cookies in production and a single trusted application origin.
- Keep Supabase database credentials, server keys and session secrets server-side. Never put them in Vite variables or browser storage.
- In production keep secrets in an external, read-only mounted config file outside the repository and run the published image with `compose/compose.production.yaml` — see `docs/SECRETS.md` in the separate `time-for-everything_deploy` repository (in Russian), including its limitations: this does not protect against host root, Docker owners or a compromised backend process.
- Exclude `.env`, database dumps, logs and real child profiles from version control. Use a separate Supabase project for development.
- Apply the supplied schema and access policies before onboarding users; never run reset against production without a verified backup and explicit approval.
- Use least-privilege database roles. Backend ownership checks remain necessary even when RLS is enabled.
- Verify authentication, refresh/logout, RLS and concurrent transactions against your Supabase project before real use. SQLite/mocked-provider tests are not a substitute.
- Keep dependencies updated and run the test suite after updates. Do not expose development servers publicly.

## Known boundaries

The preserved `prototype/` is a local visual demonstration with editable browser data and simulated authentication. It must not be used for real child accounts or secrets. It is excluded from the production Docker image.

The owner must select a project license, confirm rights to supplied images and establish retention/backup/deletion procedures before public release.
