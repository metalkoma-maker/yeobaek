# Yeobaek
- Korean novel writing app: Flask, SQLite, plain JavaScript/CSS.
- Keep existing PC web; plan an iPhone app for personal testing before App Store release.
- Preserve ownership checks, CSRF, version conflicts (409), local drafts, explicit save after loading recovery B, and history (50 prior versions).
- Never commit real manuscripts, user records, admin_config.json, credentials, rclone.conf, or backups. Use synthetic data and a temporary DB for tests.
- End-to-end encryption was deferred. The server operator can technically read stored manuscripts.
- Commits alone do not authorize production deployment or production database writes. A direct user request to deploy specific changes to production authorizes that release, including its reviewed database migration steps.
- Do not execute backup scripts in development: they use production paths and prune old backups.
- Tests: python -m unittest discover -s tests -v
- Korean UI, body fonts 10/12/14/16/18 pt, default 12 pt.

## Chat-first workflow
- Prefer workflows that let the user request, review, test, and finish development through the Codex chat. Perform available repository, test, preview, log inspection, and authorized deployment steps directly with Codex tools and existing GitHub Actions.
- Do not make the user switch between Codex, Codespaces, PowerShell, SSH, and browser settings or copy commands when Codex can perform the step. Prefer an automated or Codex-managed preview and provide a usable review link in chat.
- If a step genuinely requires the user's device, account authentication, or initial permission setup, complete all independent work first. Explain why the step cannot be automated and give the smallest set of user actions together; continue the work after receiving the result.
- Verify preview and deployment results with available tools before sharing links. Clearly distinguish verified results from checks that the current environment cannot perform.
- Treat a clear user request such as “운영에 반영해” or “운영 배포해” as approval for that production deployment. Do not ask for a second explicit approval or confirmation for the same release; use the available deployment workflow and verify the result.
- Keep existing backup, health-check, and rollback safeguards. Require a separate direct user request for unrelated destructive changes to production data.
