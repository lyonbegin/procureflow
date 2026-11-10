# ChatGPT Android Remote Relay — Google Drive link delivery

The Railway API test console orchestrates one accessibility-based Android controller
running the **unmodified official ChatGPT app**. Several web users can own
distinct API rooms and queue messages.

## File workflow (current)

1. Create an API user and connect **that user's Google Drive** via OAuth.
2. Create a chat room; the server creates `ChatGPT Relay - {user_id}/{room_name} [{room_id}]` in that user's Drive.
   For rooms created before Drive connection, use `POST /api/v1/drive/rooms/{room_id}/folder`.
3. Upload an image or other supported file through `POST /api/v1/drive/files`,
   specifying `user_id`, `room_id`, `file`, and optionally `share_link=true`.
   The file is streamed to Google Drive. Only Drive metadata and SHA-256 are saved
   in the Railway database; the file bytes are **not** stored by this endpoint.
4. To let ChatGPT access an otherwise private Google Drive file by URL,
   explicitly allow `share_link=true`. **This creates a file link that anyone with
   the URL can read. Do not enable it for sensitive documents.**
5. `POST /api/v1/rooms/{room_id}/messages` with `attachment_ids`
   builds a text-only Android job containing the Google Drive file links.
   It sends `attachment_ids=[]` to Android: **no + button, file picker,
   FileProvider or Android binary-upload path is invoked by API jobs.**
6. A Google Drive link is **not the same as an image attachment**. The official
   ChatGPT app may or may not retrieve the actual file contents. Our prompt
   requires it to explicitly disclose when it cannot read the link.

The former `POST /api/v1/files` local upload remains for backwards-compatible
retrieval; those legacy files are rejected when supplied in new message jobs.

## One-time OAuth configuration in Railway

Configure an OAuth client in Google Cloud Console (Web application):

- Enable Google Drive API in the Google Cloud project.
- Configure OAuth consent screen and add applicable Google test users while
  in testing mode.
- Register the **exact** authorized redirect URI:
  `https://chatgpt-relay-web-production.up.railway.app/api/v1/drive/oauth/callback`
- Set Railway environment variables:
  - `GOOGLE_OAUTH_CLIENT_ID` — web OAuth client ID.
  - `GOOGLE_OAUTH_CLIENT_SECRET` — web OAuth client secret (keep private).
  - `DRIVE_TOKEN_ENCRYPTION_KEY` — valid Fernet key (already provisioned
    on Railway for this deployment). Keep unchanged or existing encrypted
    tokens become unreadable.
  - `GOOGLE_OAUTH_REDIRECT_URI` — optional if RAILWAY_PUBLIC_DOMAIN resolves correctly.

The scope is `https://www.googleapis.com/auth/drive.file`: the app
can work with files/folders that it creates or that the user specifically
opens with this application. The refresh token is encrypted on the
persistent Railway volume and is never included in web API responses.

`GET /api/v1/drive/status?user_id=...` reports whether OAuth is configured
and whether the particular user has connected their Drive.
`POST /api/v1/drive/connect?user_id=...` returns the Google authorization URL.
The web tester has buttons for this flow.

## Authentication and safety

- Keep the `CONSOLE_TOKEN` and `DEVICE_TOKEN` in Railway separate.
- The public HTML no longer contains a default administrator token. The
  test console saves a manually entered token only in the local browser,
  not in the HTML response. Use user-specific API Keys for Drive work.
- Before real multi-user operation: rotate any previously exposed shared
  console token, implement proper end-user authentication and rate limiting,
  and review Google Drive link-sharing privacy.
- Google OAuth credentials configured in Railway do **not** originate from
  a ChatGPT connected Google Drive account; those authorizations cannot
  be transferred into Railway.
- Existing ChatGPT conversation switching still requires a verified matching
  previous message and may fail if Android can't identify the room.
- Do not use this prototype with confidential documents without security review.

## Services

Railway root: `/chatgpt-android-relay/web`
Web: `https://chatgpt-relay-web-production.up.railway.app/`
OpenAPI: `https://chatgpt-relay-web-production.up.railway.app/docs`
Health: `/health`
Android WS: `/ws`

API tests: `web/tests/test_api_v1.py` and
`web/tests/test_drive_v1.py`. The Drive test replaces Google's HTTP API
with a strict mock; an OAuth connection to a real Google account is not
verified by CI.
