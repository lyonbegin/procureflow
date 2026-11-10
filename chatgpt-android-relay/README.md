# ChatGPT Android Remote Relay — verified integration boundary

The Railway web API queues per-user, per-room jobs for a **separate Android
AccessibilityService controller**. It interacts with the **unmodified official
ChatGPT Android app**. Web/API authorization is NOT equivalent to ChatGPT
sign-in; the official app still needs its own authenticated session.

## Current evidence (2026-11-11, Korea)

| Test | Status | Evidence |
| --- | --- | --- |
| Install/start the user's official ChatGPT 1.2026.300 split APK on x86_64 emulator | PASS (install and launch only) | [prior isolated run](https://github.com/lyonbegin/backend/actions/runs/42829972766) |
| Build/install controller on Android 15 x86_64, bind accessibility service, show live status, no fatal crash | PASS | [controller CI](https://github.com/lyonbegin/procureflow/actions/runs/42843528062) |
| Server test for authenticated user scoping, room identity, jobs, file-byte transport and adversarial acknowledgements | PASS, simulated device | [server CI](https://github.com/lyonbegin/procureflow/actions/runs/42904314954) |
| Official ChatGPT signed-in new conversation; capture real conversation ID | **NOT TESTED** | Authentication screen blocked prior emulator testing |
| Real conversation A→B→A / repeated sends / extracted live assistant answer | **NOT TESTED** | Requires authenticated official app |
| Actual image/PDF selection and preview within signed-in ChatGPT composer | **NOT TESTED** | Server binary-transfer test is not app-picker proof |

The server's test WebSocket device deliberately sends simulated job results;
therefore a green server CI badge **does not prove actual ChatGPT UI success**.
The earlier official app run displayed a login screen and an emulator launcher
ANR. Never label composer visibility, link dispatch or API queue success as
successful message delivery.

The branch `fix/chatgpt-relay-verified-routing-20261110` and
[Draft PR #35](https://github.com/lyonbegin/procureflow/pull/35)
are isolated; **do not merge or deploy to production** before genuine end-to-end
verification. Do not ask the user to reinstall an unverified APK.

## Primary file workflow — original bytes, no Google Drive required

1. Create an API user and a room using `POST /api/v1/users` (admin) and
   `POST /api/v1/rooms` (user key).
2. Upload real binary files using `POST /api/v1/files` (one per request),
   or upload several files plus the question atomically with
   `POST /api/v1/rooms/{room_id}/turns` (multipart/form-data, `files` fields).
3. Alternatively enqueue `POST /api/v1/rooms/{room_id}/messages` with
   `text` and previously uploaded `attachment_ids`.
4. The server stores the bytes on the configured Railway filesystem,
   checks file ownership/room membership, and sends file IDs, metadata and
   SHA-256 digests in the job over the authenticated Android WebSocket.
5. The controller retrieves each file's **original bytes** using
   `GET /api/v1/device/jobs/{job_id}/files/{file_id}` with `DEVICE_TOKEN`;
   it stages a uniquely named file in Android Downloads/MediaStore.
6. Android code attempts to open the **current conversation's composer**
   attachment control, select the staged file and verify a preview before
   sending the prompt. **This final real-app UI flow is unverified.**

Maximum permitted file size is **15 MiB per file**, up to **10 files per turn**.
The supported extension allowlist is defined in `web/api_v1.py`.
Files are NOT reconstructed from a public URL. Server-side byte-for-byte and
SHA-256 tests pass, but that does not establish actual ChatGPT attachment acceptance.

## Room identity and anti-misrouting

- Link an existing private conversation with `chatgpt_url` in a room.
  `https://chatgpt.com/c/{conversation-id}` is supported;
  public `/share/` snapshots are deliberately rejected.
- A deep link opening a visible composer is **insufficient proof** that
  Android arrived at the requested conversation. Verified conversation-specific
  historical message anchors are required; otherwise return
  `UNVERIFIED_CONVERSATION` and do not send.
- The server now refuses any successful device acknowledgement with a missing
  or wrong `room_id` (`ROOM_ID_MISMATCH`). It uses the server-side
  job→room mapping for state updates, never a device-supplied target.
- Job completion must match an **action-specific verification stage**:
  `room.open` requires `room_open_verified`; `chat.send` and
  `room.bind` require `assistant_reply_stable` and non-empty reply text.
  A mere `deeplink_app_landed` signal fails with
  `UNVERIFIED_JOB_COMPLETION`. These are checks of the device report,
  **not proof the official app really produced that report**.
- Replacing an Android device WebSocket invalidates the old session.
  Previously in-flight work is marked `connection_lost` and never
  retried without an explicit user action. A stale socket may not mutate
  newer jobs.
- On first device connection after a server restart, previously persisted
  `running` jobs are failed with `server_restarted`. This relay assumes
  a **single server worker and one Android controller**, not multi-instance
  shared job processing.
- Queued jobs with missing original input file bytes fail with
  `input_file_unavailable` instead of preventing later jobs from running.
- Changing `chatgpt_url` is blocked while that room has queued/running
  jobs. A successful later change resets the prior Android verification
  and obsolete room titles.
- The old ChatGPT app login and system ANR screens are explicitly blocked;
  failure is reported rather than searching for a composer on those screens.

## Optional legacy Google Drive workflow

Old shared Drive links are supported only when the user explicitly opted to
share a file publicly. Those files are delivered as **text URLs**, not as
native ChatGPT attachments. Do not confuse this legacy mode with the primary
binary file workflow. Google Drive OAuth is optional for the primary workflow.

To configure optional Drive OAuth, supply `GOOGLE_OAUTH_CLIENT_ID`,
`GOOGLE_OAUTH_CLIENT_SECRET`, `DRIVE_TOKEN_ENCRYPTION_KEY` and, if needed,
`GOOGLE_OAUTH_REDIRECT_URI`. The redirect registered with Google is:
`https://chatgpt-relay-web-production.up.railway.app/api/v1/drive/oauth/callback`.
`drive.file` scope is used. Do not change the encryption key if there are
existing encrypted refresh tokens. The connected ChatGPT Google Drive
connector does not grant the Railway service Google OAuth access.

## Authentication and deployment safety

- `CONSOLE_TOKEN`, per-user API keys and `DEVICE_TOKEN` have different
  scopes. `WEB_SESSION_SIGNING_KEY` signs web sessions.
- Never embed production credentials in the Android source, static HTML or
  test artifacts. Previously committed device credentials may still exist
  in historical revisions: plan a **coordinated credential rotation**
  before production use; do not silently break deployed clients.
- A logged-out official ChatGPT Android app cannot perform real conversation
  testing. Do not treat a server-simulated `verified: true` as Android proof.
- Do not use this experimental controller with confidential data until the
  authentication, per-user access control and production security are reviewed.

## Services and isolated test commands

Railway web: `https://chatgpt-relay-web-production.up.railway.app/`
(health: `/health`, OpenAPI: `/docs`, Android WebSocket: `/ws`).
The Railway service root is `/chatgpt-android-relay/web`.

Run server regression tests independently:

```bash
python -m pip install -r chatgpt-android-relay/web/requirements.txt
python chatgpt-android-relay/web/tests/test_api_v1.py
python chatgpt-android-relay/web/tests/test_drive_v1.py
```

CI: `.github/workflows/verify-chatgpt-relay-api-contract.yml` (API)
and `.github/workflows/verify-chatgpt-relay-verified-routing.yml`
(Android 15 controller). Neither test suite signs in to the official ChatGPT
application. The controller APK is deliberately **unpublished**.
