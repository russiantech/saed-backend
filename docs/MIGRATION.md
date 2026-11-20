# Data migration notes

**Back up first** (`pg_dump`/copy `db.sqlite3` and the media folders). Migration `0004` removes the old module / fast-track tables and `Course.price`; it cannot be undone without the backup.

| Migration | What it does |
|---|---|
| `0001_initial` | Baseline of the previous schema (use `migrate --fake-initial` if your database already has those tables). |
| `0002_unified_lessons_payments_schema` | Additive only: `Course.public_id` (UUID), `course_type`, `is_published`, training fields; `Lesson` fields (price, lock, scheduled date/time, private files, video-fee flags); new `Payment`, `WebhookEvent`, `LessonAccess`; `Notification.link`. |
| `0003_migrate_modules_fasttrack_to_lessons` | Data migration (see below). |
| `0004_drop_modules_fasttrack_course_price` | Drops modules, module access, fast-track, trainer-feature-payment tables and `Course.price`. |

### What happens to existing data (0003)
* Every course gets a UUID `public_id`; **all existing active courses are published** so nothing disappears.
* Module lessons become course lessons, renumbered in module order. A locked, priced module is **split evenly across its non-free-preview lessons, each share rounded up to a whole naira** (₦3,000 over 2 lessons → two ₦1,500 locked lessons; ₦1,000 over 3 → three ₦334 lessons, so the total can rise by at most ₦(n−1)). Former free-preview lessons and free modules stay free. A lesson that belonged to neither a course nor a module is deleted.
* Paid **module access** records (`status=success`, verified) become **active lesson access** (`source=legacy_module`) to every lesson of that module for the same corps member, so nobody who paid loses content.
* Fast Track videos are appended as video lessons at the end of their course (price kept; locked when priced and not a free preview). Their video-upload fee is recorded as already paid, so trainers are not charged again.
* Past trainer feature payments are preserved as `legacy_feature` payments (history, not re-charged).
* Enrolments, progress, connections, notifications and payment references on enrolments are kept.
* Uploaded files from the old system keep working: legacy URLs under `/media/uploads/videos|documents|lessons/` are resolved by the streaming endpoint (still behind the entitlement check). Optionally move them into `PRIVATE_MEDIA_ROOT` and re-save the lesson to get fully private storage.

### Verification after migrating
```bash
python manage.py check
python manage.py makemigrations --check --dry-run   # must report no changes
python manage.py shell -c "from saed.models import *; print(Course.objects.count(), Lesson.objects.count(), LessonAccess.objects.count(), Payment.objects.count())"
```
Compare course/lesson/enrolment counts with the pre-migration database.

### Public links
Course URLs are now UUIDs. Old integer URLs still resolve (`/api/courses/<int>/`, `/app/programs/<int>` redirects), so old emails keep working.


## 0005 – partnership letters move to private storage
Schema-only (storage backend of `Profile.partnership_letter`); no data is changed. After migrating run `python manage.py move_partnership_letters` once to move existing letter files from `MEDIA_ROOT/partnership_letters/` into `PRIVATE_MEDIA_ROOT`. Until then they are still served (privately, through the API) from the old location. Rows whose file no longer exists are reported by the command and shown in the UI as "file missing – upload again".


## 0006 – performance indexes
Schema-only: composite indexes on courses, lessons, enrolments, notifications and profiles. Safe to apply on a live database (they build in well under a second at normal size; on very large tables apply during a quiet period).


## 0007 – streams and tracks (schema)
Adds `Stream`, `StreamMembership`, `OrientationCamp.stream`, `Course.stream`, `Course.approval_status/review_note/reviewed_at/reviewed_by`, and narrows `Profile.account_mode` to `in_camp`/`post_camp`.

## 0008 – streams (data)
Derives streams from existing data, reversible as a no-op:
* Camps with identical start/end dates become one Stream per year (numbered by start order, capped at 6); courses are linked through their camp.
* Corps members that were "both" become In-Camp if their camp has a stream, otherwise Post-Camp (membership active or expired by date).
* Trainers whose courses are all In-Camp with streams become In-Camp with memberships; all others become Post-Camp.
* Existing courses default to `approval_status=approved`, so nothing disappears.
Review the result in *Admin → Streams* and adjust numbers/dates as needed. **Schedule `python manage.py deactivate_incamp` daily** (cron/Task Scheduler) so expiries are recorded and notified; access is blocked on time even without it.
