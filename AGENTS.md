# Yeobaek
- Korean novel writing app: Flask, SQLite, plain JavaScript/CSS.
- Keep existing PC web; plan an iPhone app for personal testing before App Store release.
- Preserve ownership checks, CSRF, version conflicts (409), local drafts, explicit save after loading recovery B, and history (50 prior versions).
- Never commit real manuscripts, user records, admin_config.json, credentials, rclone.conf, or backups. Use synthetic data and a temporary DB for tests.
- End-to-end encryption was deferred. The server operator can technically read stored manuscripts.
- Commits do not authorize production deployment or production database writes.
- Do not execute backup scripts in development: they use production paths and prune old backups.
- Tests: python -m unittest discover -s tests -v
- Korean UI, body fonts 10/12/14/16/18 pt, default 12 pt.
