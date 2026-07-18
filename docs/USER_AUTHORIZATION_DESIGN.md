# User Authentication, Authorization, and Data Isolation Design

## Goals

- Provide local username/password signup and login without an external identity provider.
- Support `superuser`, `admin`, and `user` roles.
- Let an admin manage only users assigned to that admin; let the superuser manage everyone.
- Grant new users every normal application feature except Stock Grabber.
- Enforce permissions in both the API and UI.
- Isolate TMS accounts, scheduled orders, logs, holdings, strategy plans, saved views, and research runs by application user.
- Reuse identical completed backtest computation without exposing another user's metadata or activity.
- Preserve all existing data during migration.

## Account hierarchy

`superuser`

- Global account created from `FRONTEND_SEED_USER` / `FRONTEND_SEED_PASSWORD` (defaults remain `admin` / `admin`).
- Has every permission and can manage all admins and users.
- Owns all legacy rows that existed before ownership was introduced.

`admin`

- Created by the superuser or seeded from `FRONTEND_ADMIN_USER` / `FRONTEND_ADMIN_PASSWORD`.
- Can list, create, disable, reset, and configure users whose `managed_by_user_id` points to that admin.
- Can promote a managed normal user to the all-feature `superuser` role and later revoke that role; only the root superuser can create another administrator.
- Cannot modify users belonging to another admin or an unassigned superuser.

`user`

- Created through signup or by an admin.
- A self-signup user is assigned to the configured default admin when one exists.
- Can update only their own profile/password and use permitted features.

## Permissions

Permissions use stable feature keys rather than route labels:

- `order_logs`
- `schedule_orders`
- `portfolio`
- `market_analysis`
- `stock_grabber`
- `strategy_details`
- `backtest`
- `recommendations`
- `stock_table`
- `edis`
- `settings`
- `tms_login`
- `admin_users`

Defaults grant every feature except `stock_grabber` and `admin_users`. Superusers always resolve to all permissions. Admins receive `admin_users` in addition to their configured feature set. Permission changes increment `token_version`, immediately invalidating existing tokens for that user.

## Password and session security

- Passwords are stored as versioned PBKDF2-HMAC-SHA256 hashes with a per-user random salt.
- Successful login returns an HS256 JWT containing only user ID, username, role, token version, issued time, expiry, and a random token ID. Passwords are never embedded in tokens.
- Tokens expire after the configured lifetime and are rejected when the account is disabled or its token version changes.
- Login and CAPTCHA verification use constant-time comparisons.

## Signup CAPTCHA

- `GET /api/auth/captcha` creates a random arithmetic challenge.
- Only a SHA-256 digest of the normalized answer plus a server nonce is stored.
- Challenges expire, are single-use, and have a maximum attempt count.
- Signup consumes a valid challenge in the same transaction as account creation.
- CAPTCHA limits basic automated signup; it is intentionally not presented as equivalent to a managed anti-abuse provider.

## Ownership model

- `users.owner_user_id` is the authoritative owner of a TMS account.
- Operational tables also receive `owner_user_id` for direct, indexed authorization and auditability.
- Existing TMS and operational rows are assigned to the seeded superuser non-destructively.
- Every sensitive API resolves the authenticated user and filters rows by `owner_user_id`.
- Admin user-management access does not automatically grant access to a managed user's trading data. Admin impersonation is not supported.
- Shared market OHLCV, indicator history, security classifications, and preset definitions remain global read-only research data.

## Backtest reuse

- The scan identity is based on immutable strategy, universe, engine, cost, and data configuration—not the requesting user or display name.
- If the same owner requests the same scan, the existing owner run is continued only for newer sessions.
- If another owner already has a completed identical scan through the required session, the service creates a lightweight owner-specific run and copies normalized result/trade references or rows transactionally. User-entered run name, notes, saved views, AI audit, and ownership remain private.
- No endpoint returns another owner's run metadata merely because computation was reused.

## Audit

`frontend_user_audit_log` records authentication and administrative events including actor, target, action, before/after metadata, IP, user agent, and timestamp. Passwords, CAPTCHA answers, tokens, and TMS secrets are never recorded.

## API surface

Public:

- `GET /api/auth/captcha`
- `POST /api/auth/signup`
- `POST /api/auth/login`
- health/time endpoints and frontend assets

Authenticated:

- `GET /api/auth/me`
- `POST /api/auth/logout`
- `POST /api/auth/change-password`

Admin:

- `GET /api/admin/users`
- `POST /api/admin/users`
- `PATCH /api/admin/users/{id}`
- `POST /api/admin/users/{id}/reset-password`
- `GET /api/admin/users/{id}/activity`

## UI

- The root route contains Sign in and Create account modes.
- Signup includes username, password confirmation, CAPTCHA, and refresh challenge.
- Dashboard navigation is built from `/api/auth/me`; forbidden tabs are not rendered and direct navigation redirects to the first permitted route.
- Admins see a User Access page with status, role, manager, last login, created date, permission toggles, reset-password, and activity history.
- Stock Grabber is absent for new users until an authorized administrator explicitly enables it.

## Migration and rollout

- Schema changes use `ADD COLUMN IF NOT EXISTS`, backfills, and indexes; no tables or rows are deleted.
- The existing seeded account becomes the superuser and its plaintext password is upgraded to a hash on startup/login.
- Existing operational data is assigned to that superuser.
- Authentication enforcement is enabled only after the frontend automatically attaches the bearer token to same-origin API calls.
- Docker volumes and existing database contents remain untouched.
