# Changelog

All notable changes to Cloze. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

Cloze is still in 0.x: a minor release (0.6 → 0.7) can change behaviour, settings and the database, and its **Upgrade** section says what to do. Version 1.0.0 will mark the redesigned participant interface as the default.

## [Unreleased]

## [0.6.0] - Unreleased

The first stage of the participant redesign, a researcher media library, and a round of safety and security fixes. **The new participant interface is opt-in**: participants keep today's pages until an admin turns it on.

### Upgrade
1. **Back up the database.**
2. **Run `python migrate_schema.py --apply` before starting this version.** If the new code runs against the old schema, participant pages fail. Run it without `--apply` first to see what it will do. The migration:
   - adds columns:
     - `chat_templates.flow_chat_id`;
     - `flow_chats.greeting_text` and `greeting_asset_id`;
     - `provider_feature_flags.greeting_text`, `greeting_asset_id` and `access_hours_mode`;
     - `conversations.ended_at` and `end_reason`;
     - `messages.client_message_id`;
   - adds a unique index on `messages (conversation_id, client_message_id)`;
   - creates the `media_assets` and `media_renditions` tables;
   - links existing participant chats to their study-design chats;
   - records conversations in chat windows that have already ended as finished.
3. **Check `CLOZE_PROXY_HOPS`.** This new setting is the number of proxies in front of the app, used to find the client's IP for sign-in rate limiting. It defaults to 1, which suits Cloudflare in front of gunicorn. Set it to match your deployment.
4. **Optional: `CLOZE_MEDIA_BUCKET`** turns on the researcher media library (stored in S3). The Terraform module sets it. Without it, production instances switch uploads off.
5. **Optional: the new participant interface.** Set the admin setting `participant_ui` to `v2`, for example with `POST /api/admin/settings {"participant_ui": "v2"}`. Set it back to `v1` to roll back. With `v2`, researchers and admins also sign in on the new sign-in page.

### Added
- **The redesigned participant interface (opt-in, `participant_ui = v2`).** It includes:
  - a study menu (a rail on computers; a top bar and tabs on phones) and Home;
  - an exercise page with a one-line reply box;
  - a Notebook side panel, with Save to notebook on selected text, and a Notebook page with the participant's own notes;
  - a Safety plan page with Save for later;
  - a Reports page;
  - Get help now on every page;
  - a new sign-in page;
  - a closed-hours screen.

  It works with a keyboard and on phones, follows the instance's colours (`CLOZE_THEME`) in light and dark mode, and uses a self-hosted Figtree font.
- **Closed hours:** researchers choose between the resting screen (`lock`, the default) and `read_only`, which keeps chats readable.
- **Why a conversation ended:** conversations record when and why they ended (`turn_limit`, `window_closed`). An ended conversation stays ended.
- **Researcher media library**, stored in S3, and a **greeting** in empty chats, set per researcher and per chat.
- **Participants' notes on saved lines:** `PUT /api/selections/<id>`. `GET /api/selections` also returns `own_note` and `conversation_title`.

### Changed
- **Sending, on the new interface:**
  - the participant's message is saved before the model is called;
  - a failed reply can be retried without sending the message twice;
  - a reply blocked by the provider's safety filter is answered with a pointer to 988 and Get help now.
- **CLOZE-Guard** scans every participant message before any check that can refuse it, and a failure inside Guard never blocks a message.
- **Messages** are limited to 10,000 characters; saved lines to 20,000 characters and notes to 1,000.
- **The participant pages** read settings and menu data once per request, which halves or thirds their database queries.

### Fixed
- The model was sent the first 20 messages of a conversation instead of the latest 20, and in shorter conversations it got the newest message twice. This affected today's interface too.
- Deleting a study phase that participants were enrolled in failed on Postgres.
- A study chat lost its model when that model wasn't currently available.
- Report PDFs couldn't be written with pydyf 0.11 or later; pydyf is now pinned below 0.11.
- The 403, 404 and 500 pages now show 988 and 911.

### Security
- **Reports:** participants can read only their own summary reports, from chat windows still visible to them, while their study has reports on. The live report endpoint is for the research team only.
- **Sending:** only a conversation's own user can send in it.
- **Sign-in:**
  - every refusal (unknown username, wrong password, locked account) gets the same response;
  - an expired lock starts the count over;
  - sign-in rate limiting uses the real client IP and counts only failed attempts.
- **Chats:** hidden chats can't be started through the API.
- **Safety plan input** is checked on the server.
- **Injected text:**
  - model replies, report text and admin-entered fields are escaped or sanitised (marked and DOMPurify, pinned with integrity hashes);
  - a study's raw-HTML safety text is limited to text and links;
  - report PDFs can't load local files or fetch URLs.
- **Errors and docs:** report errors are logged on the server instead of being shown, and `/docs` and `/openapi.json` are served in development only.

## [0.5.1] - 2026-10-28

Calmer safety alerts and per-instance colour themes (`CLOZE_THEME`).

## [0.5.0] - 2026-10-28

The first release from cloze-platform:
- Terraform for a complete single-instance deployment on AWS;
- repository cleanup;
- a fix that stops conversations getting around the composed safety prompt.

## [0.4.0] - 2026-07-30

The cloze.uk production baseline.

[Unreleased]: https://github.com/cloze-platform/cloze/compare/v0.5.1...HEAD
[0.6.0]: https://github.com/cloze-platform/cloze/compare/v0.5.1...HEAD
[0.5.1]: https://github.com/cloze-platform/cloze/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/cloze-platform/cloze/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/cloze-platform/cloze/releases/tag/v0.4.0
