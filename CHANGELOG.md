# SAED IMS — Changelog

## Sept 18, 2026 — UX Improvements, Bug Fixes & Feature Completion

### Bug Fixes
| # | Fix | Files |
|---|-----|-------|
| 1 | Naira symbol (`₦`) rendering as `\u20a6` literal in JSX strings — replaced with actual Unicode character | `TraineeFastTrack.jsx`, `FastTrackVideos.jsx` |
| 2 | Enrollment management grid misaligned (4-column template for 3-column layout) — added `.enrollment-management` override | `ManageApplications.jsx`, `styles.css` |
| 3 | History stack buildup on ProgramDetail login redirect — added `replace: true` to `navigate()` | `ProgramDetail.jsx` |
| 4 | Race condition on enrollment status — enroll button shown before API loads, causing double-submissions | `ProgramDetail.jsx` |
| 5 | Python 3.14 SSL `SSLV3_ALERT_BAD_RECORD_MAC` on Paystack API — switched to `http.client` with custom SSL context and 3-attempt retry | `payments.py` |

### UX Improvements
| # | Change | Files |
|---|--------|-------|
| 6 | Forgot password redesigned to match signup email verification style — 6-digit code boxes with auto-advance, paste support, and 60s resend cooldown | `ForgotPassword.jsx` |
| 7 | Back button (`← Back to Home`) added to `/programs`, `/activities`, `/opportunities` public pages | `Programs.jsx`, `Activities.jsx`, `Opportunities.jsx` |
| 8 | Explore nav link now goes to `/login` with `redirectTo: "/app/programs"` — users land on courses after login | `FloatingNav.jsx` |
| 9 | Login no longer auto-enrolls via `pendingProgramId` — user clicks enroll on the course detail page instead | `Login.jsx` |
| 10 | Enrollment status works on public routes (removed `!inApp` gate) — non-logged-in users see "Enroll" button | `ProgramDetail.jsx` |
| 11 | Abandoned payment retry — pay button shows again instead of "Enrollment pending" when enrollment exists without payment | `payments.py` |

### New Features
| # | Feature | Files |
|---|---------|-------|
| 12 | Lesson completion tracking — `LessonProgress` model (migration 0033) tracks which lessons each student has completed | `models.py`, `0033_lesson_progress.py` |
| 13 | Progress API — `GET /courses/:id/progress/` returns totalLessons/completedLessons/percentage; `POST /courses/:id/lessons/:id/complete/` marks a lesson done | `courses.py`, `urls.py` |
| 14 | Fast track videos endpoint returns `completedLessonIds` for enrolled students | `fast_track.py` |
| 15 | TraineeFastTrack shows "Mark Complete" button per lesson, completion counter (`3/12 completed`), and "Done" badge for completed lessons | `TraineeFastTrack.jsx` |
| 16 | Enrollment management page simplified — only Student, Course, Progress columns, sorted by last name then course | `ManageApplications.jsx` |
| 17 | Enrollment auto-confirmed — free courses confirmed immediately, paid courses confirmed after Paystack verification (no trainer approval needed) | `payments.py`, `programs.py` |

### Removals
| # | What | Files |
|---|------|-------|
| 18 | Trainer confirm/reject enrollment endpoints removed (`TrainerPendingEnrollmentsView`, `TrainerConfirmEnrollmentView`, `TrainerRejectEnrollmentView`) | `payments.py`, `__init__.py`, `urls.py` |
| 19 | Pending Enrollments tab removed from trainer CourseManagement and FastTrackVideos pages | `CourseManagement.jsx`, `FastTrackVideos.jsx` |

### Infrastructure
| # | Change | Files |
|---|--------|-------|
| 20 | Sensitive test artifacts (`cookies5.txt`, `*.json`) gitignored in backend | `.gitignore` |
| 21 | `.tools/` directory gitignored in frontend | `.gitignore` |

---

## Sept 11, 2026 — End-to-End Test Results

### All Flows Verified Working
| Flow | Status | Notes |
|------|--------|-------|
| Corps member signup | ✅ | Correctly validates all required fields |
| Email verification | ✅ | Token-based, blocks login until verified |
| Login (verified) | ✅ | Session-based auth |
| Login (unverified) | ✅ | Returns 403 with email_not_verified |
| Password reset (3-step) | ✅ | Request → verify code → reset password |
| Old password after reset | ✅ | Correctly rejected |
| Profile update | ✅ | PATCH method |
| Dashboard | ✅ | Role-specific stats |
| Notifications | ✅ | Role-filtered, unread count accurate |
| My Courses | ✅ | Shows enrolled courses |
| Programs | ✅ | List + categories |
| Application creation | ✅ | Links to program |
| Connect trainer | ✅ | Creates pending connection |
| Connections (corps) | ✅ | Lists corps member's connections |
| Connections (trainer) | ✅ | Via TrainerCorpersView |
| Trainer courses | ✅ | CRUD |
| Trainer dashboard | ✅ | Stats + programs |
| Admin users list | ✅ | All users |
| Admin courses | ✅ | All courses |
| Admin refunds | ✅ | Empty list (no refunds yet) |
| Admin notifications | ✅ | Role-filtered |
| Program creation | ✅ | Admin creates with trainer assignment |
| Complaint submission | ✅ | |
| Trainer authorization | ✅ | Admin approves trainer |
| Trainer connection approve | ✅ | Status → active |
| Logout | ✅ | Session destroyed, cookie removed |
| Post-logout access | ✅ | Returns 401 |
| LGA filter | ✅ | Fixed SQLite compatibility |

### Bug Found During E2E
| # | Fix | Files |
|---|-----|-------|
| 1 | LGA filter `__contains` on JSONField broken with SQLite — changed to `__icontains` | `trainers.py` |

---

## Sept 11, 2026 — Deep Audit Fixes

### Critical Bug Fixes
| # | Fix | Files |
|---|-----|-------|
| 1 | Fixed `UnboundLocalError` — `token` undefined when user not found in password reset | `auth.py` |
| 2 | Fixed `AttributeError` — `request.user.profile` crashes without Profile in fast track views | `fast_track.py` |
| 3 | Fixed `AttributeError` — nullable `course.trainer` not checked in refund views | `payments.py` |
| 4 | Fixed `HasTrainerRole()` — now returns proper DRF BasePermission class instead of bare function | `base.py` |

### Medium Bug Fixes
| # | Fix | Files |
|---|-----|-------|
| 5 | Fixed unsafe `int()` on untrusted input in course max_students and video order/price | `courses.py`, `fast_track.py` |
| 6 | Fixed `unreadCount` including role-filtered notifications | `notifications.py` |
| 7 | Fixed "Remove" button logic inverted between SAED/DUNIS admins | `ManageUsers.jsx` |

### Cleanup
| # | Fix | Files |
|---|-----|-------|
| 8 | Removed dead `DunisAdmin` import from AppShell | `AppShell.jsx` |
| 9 | Removed `console.error` from production API code | `api.js` |

---

## Sept 11, 2026 — Low Priority Fixes

| # | Fix | Files |
|---|-----|-------|
| 1 | LGA filtering moved from Python loop to DB query | `trainers.py` |
| 2 | DashboardView uses IsAuthenticatedAPI (was AllowAny) | `dashboard.py` |
| 3 | Duplicate title check on course creation | `courses.py` |
| 4 | Fast track video order/price/duration clamped to ≥ 0 | `fast_track.py` |

---

## Sept 11, 2026 — Medium Priority Fixes

| # | Fix | Files |
|---|-----|-------|
| 1 | My Courses page for corps members with backend endpoint | `MyCourses.jsx`, `courses.py`, `urls.py` |
| 2 | Notifications uses IsAuthenticatedAPI (was AllowAny) | `notifications.py` |
| 3 | Partnership letter file type validated (PDF/JPG/PNG only) | `auth.py`, `profile.py` |
| 4 | Specialization validated against SKILL_AREAS on signup | `auth.py` |
| 5 | Password reset invalidates all user sessions | `auth.py` |
| 6 | Removed orphan FindTrainers.jsx page and route | `index.js` |

---

## Sept 11, 2026 — High Priority Fixes

| # | Fix | Files |
|---|-----|-------|
| 1 | Admin refund management page with process/deny actions | `AdminRefunds.jsx`, `index.js`, `AppShell.jsx` |
| 2 | Trainer authorization gate — HasTrainerRole() requires is_authorized + has_paid + payment_verified | `base.py`, `courses.py`, `fast_track.py`, `payments.py`, `trainers.py` |
| 3 | admin_update notifications visible to admins (was filtered from ALL users) | `notifications.py` |
| 4 | Rate limiting on LoginView, ResendVerificationView, PasswordResetRequestView | `auth.py`, `settings.py` |

---

## Sept 10, 2026 — Session Changelog

### Auth & Verification Fixes
| # | Fix | Files |
|---|-----|-------|
| 1 | AdminSignup no longer calls `login(userPayload)` after signup | `AdminSignup.jsx` |
| 2 | Trainer auto-login removed — trainers must verify email | `auth.py` |
| 3 | Password reset code expires after 15 minutes | `auth.py`, `models.py` |
| 4 | VerifyEmail double-fire in StrictMode fixed | `VerifyEmail.jsx` |
| 5 | `signup()` no longer sets user state without server session | `auth.jsx` |
| 6 | Trainer username used from form (was replaced with email) | `auth.py` |
| 7 | AdminSignupView creates `saed_admin` (was `dunis_admin`) | `auth.py` |
| 8 | VerifyEmail redirects to `/login` after verification | `VerifyEmail.jsx` |

### Trainer & Payment Fixes
| # | Fix | Files |
|---|-----|-------|
| 9 | ConnectTrainer: `connectionStatus === null` → `"none"` | `ConnectTrainer.jsx` |
| 10 | Course category sends keys not display labels | `CourseManagement.jsx` |
| 11 | IDOR fix: CorperProfileForTrainerView requires active connection | `trainers.py` |
| 12 | enrolledCount counts per-course enrollments | `trainers.py` |
| 13 | Paystack amount verified against course price | `payments.py` |
| 14 | Payment shows "Pending Confirmation" (was "Paid" immediately) | `ConnectTrainer.jsx` |
| 15 | TraineeFastTrack preserves `enrollmentStatus` after payment | `TraineeFastTrack.jsx` |
| 16 | Slot check uses per-course enrollment count | `trainers.py` |
| 17 | Rejected/refunded enrollments can't be re-verified | `payments.py` |
| 18 | Enrollment confirm checks max_students capacity | `payments.py` |
| 19 | FastTrackVideo URL validation added | `fast_track.py` |
| 20 | Course deletion blocked if active enrollments exist | `courses.py` |

### Admin Fixes
| # | Fix | Files |
|---|-----|-------|
| 21 | AdminCourses link added to sidebar | `AppShell.jsx` |
| 22 | Missing models registered in Django admin | `admin.py` |
| 23 | `connection_declined` added to Notification.REASON_CHOICES | `models.py` |

### New Endpoints & Pages
| # | What | Files |
|---|------|-------|
| 24 | SAED admin signup: `/x9k2m-admin` → `/api/auth/saed-admin-signup/` | `AdminSignup.jsx`, `urls.py` |
| 25 | Dunis admin signup: `/d9x7k-admin` → `/api/auth/dunis-admin-signup/` | `DunisAdminSignup.jsx`, `auth.py`, `urls.py` |

### Infrastructure
| # | Fix | Files |
|---|-----|-------|
| 26 | `setupProxy.js` port fixed (8002 → 8000) | `setupProxy.js` |
| 27 | `AllowAny` import fixed in payments.py | `payments.py` |
| 28 | `password_reset_code_created_at` field + migration | `models.py`, migration `0026` |
| 29 | CSRF `clear_session` endpoint moved before `api/` include | `config/urls.py` |
| 30 | `HttpResponse` import added for favicon | `config/urls.py` |

### Spelling Fixes
| # | Before | After |
|---|--------|-------|
| 31 | "Religion Activities" | "Religious Activities" |
| 32 | "takes places" | "takes place" |
| 33 | "things follows" | "things follow" |
| 34 | "see direction to" | "see directions to" |
| 35 | "Number of Trained" | "Number of Trainees" |
| 36 | "Enter No of Trained Student" | "e.g. 50" |

## Admin Signup Links
| Role | Frontend | Backend |
|------|----------|---------|
| SAED Admin | `/x9k2m-admin` | `POST /api/auth/saed-admin-signup/` |
| Dunis Admin | `/d9x7k-admin` | `POST /api/auth/dunis-admin-signup/` |

## Test Results
- **28/28 backend tests pass**
- **Django system check: 0 issues**
- Frontend builds clean
- Both repos pushed to `origin/dev` and `origin/main`
