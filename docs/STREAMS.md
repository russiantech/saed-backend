# Streams, In-Camp and Post-Camp — how it works (backend)

## 1. Two programmes in one API
Every account has one **track** (`Profile.account_mode`): `in_camp` or `post_camp`. The tracks are separate products that
share code, not data:

| | In-Camp SAED | Post-Camp SAED |
|---|---|---|
| Who | corps members during orientation camp, trainers admitted to a stream | corps members after camp, independent trainers |
| Sign-up | `POST /api/auth/signup/` `accountMode=in_camp`, **`streamId` required**, no LGA/PPA | `accountMode=post_camp`, state/LGA/PPA, no stream |
| Trainer creation | by the **SAED admin** only (invite e-mail) | self sign-up (existing flow) |
| Courses | `course_type=in_camp`, belong to a stream, **approved by admin** | `course_type=post_camp`, published by the trainer |
| Visibility | only courses of the user's own live stream | only post-camp courses |
| Lifetime | the stream (+ grace days) | no end date |
| Dashboard | `GET /api/incamp/dashboard/` | existing dashboard |

Crossing over (a post-camp user opening an in-camp course or vice-versa, enrolling, discovering trainers…) returns **403**.
Trainer discovery/connection and earnings endpoints are Post-Camp only. Admins see both programmes.

## 2. Streams
`Stream`: `year`, `number` (1–6, unique with year), `label`, `start_date`, `end_date`, `deactivation_grace_days`, `is_active`, `notes`.
Status is computed from the dates: `upcoming` → `running` → `grace` → `ended` (or `closed` when `is_active=false`).
Access ends at `end_date + grace days`. Admin endpoints: `GET/POST /api/manage/streams/`, `GET/PATCH/DELETE /api/manage/streams/<id>/`.
Public (sign-up form): `GET /api/streams/` (open streams only). Camps (`OrientationCamp.stream`) and courses (`Course.stream`) belong to a stream.

## 3. Account life-cycle (`StreamMembership`)
One row per user per stream (`active` / `expired` / `deactivated`). The effective state is derived live from the dates
(`services/streams.py::lifecycle`): `active`, `upcoming`, `expired`, `none` (In-Camp user without a stream), `not_applicable` (Post-Camp, admins).

* **Expired** In-Camp users get `403` with `code: "stream_expired"` on every endpoint except the allow-list
  (`/api/auth/`, `/api/notifications/`, `/api/dashboard/`, `/api/incamp/dashboard/`, `/api/submit-complaint/`, `/api/csrf/`, `/api/health`).
* `manage.py deactivate_incamp` (daily) / `POST /api/admin/run-stream-expiry/` persist expiries and notify users; idempotent.
* **Re-activation** — a trainer admitted to another stream: `POST /api/manage/stream-trainers/<id>/reactivate/ {streamId}` (or add the trainer to the new stream). Corps members re-register per stream.
* Everything is per stream and per year: reports, filters, memberships.

## 4. In-Camp trainers (admin CRUD)
`/api/manage/stream-trainers/` — list (`?streamId=`), create (`streamId`, `fullName`, `email`, `phone`, `specialization`, optional `bio` and `password`),
`GET/PATCH/DELETE …/<id>/`, `POST …/<id>/reactivate/`, `…/deactivate/`, `…/invite/`.
The invite e-mail links to `FRONTEND_URL/forgot?email=<email>`; passwords are never e-mailed. If no password is set the account has
an unusable one until the trainer resets it. Deleting is refused (409) when the trainer owns courses — deactivate instead.

## 5. Proposals
In-Camp trainer course creation forces `course_type=in_camp`, the trainer's stream, `approval_status=pending`, unpublished.
`POST /api/manage/courses/<id>/review/ {decision: approve|decline, note}` — approve publishes and notifies the trainer; decline requires a note.
Editing a declined proposal re-submits it. Post-Camp trainers cannot create In-Camp courses and vice-versa.

## 6. Reports
`GET /api/reports/streams/?streamId=&year=` — per stream: corps members, trainers, courses, enrolments, by skill, by camp, top courses,
totals, plus a separate Post-Camp summary. `GET /api/reports/streams/export/?kind=corpers|trainers|courses&streamId=` — CSV
(spreadsheet-formula injection neutralised).

## 7. Skill-set filtering (In-Camp)
`GET /api/incamp/courses/?skill=` — empty/`mine` (default for corps members: own skills first), `all`, or a skill key/label.
Response adds `skills`, `mySkills`, `skillMode`, `selectedSkill`, `noSkillMatch`.

## 8. Data migration
`0007` adds the schema, `0008` derives streams from existing camps and assigns tracks — see `MIGRATION.md`.
