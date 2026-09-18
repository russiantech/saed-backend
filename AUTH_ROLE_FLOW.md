# SAED Role-Based Signup and Login Flow

```text
Public signup/login
        |
        v
Backend authenticates the user and returns the stored profile role
        |
        v
Frontend routes the user to the role-specific dashboard and pages
```

## Corper (`corps_member`)

### Signup

1. Open `/signup` and choose **Corps Member**.
2. Enter personal details.
3. Enter NYSC state code, Lagos deployment LGA, and skill interests.
4. Submit the form.
5. Receive an email-verification link and land on `/check-inbox`.
6. Open the link to verify the email address.
7. Log in through `/login`.

### Login and destination

- Sign in with username/email and password.
- A verified account is required.
- Successful login routes the corper to `/app`, the corper dashboard.

## Trainer (`trainer`)

### Signup

1. Open `/signup` and choose **Trainer**.
2. Enter personal details.
3. Complete trainer information: specialization, approved LGAs, experience, bio, and partnership letter.
4. Submit the trainer application.
5. Receive an email-verification link.
6. Verify the email address.
7. Wait for administrative approval and payment verification.

### Login and destination

- Sign in through `/login` with username/email and password.
- A verified account is required.
- If the trainer is not authorized or is inactive, the frontend sends them to `/app/inactive-account` (inside the protected app shell).
- An active trainer is sent to `/app`, which displays the trainer dashboard.
- Backend-protected trainer actions require authorization, payment, and payment verification.

## SAED Admin (`saed_admin`)

### Signup

- There is no public SAED-admin signup page.
- Create the account through the hidden backend endpoint `POST /_sys/ops/`.
- Supply the configured `ADMIN_SIGNUP_SECRET` and set `role` to `saed_admin`.
- The created account is email-verified automatically.

### Login and destination

- Sign in through the shared `/login` page.
- Successful login routes the SAED admin to `/app`.
- Opening `/admin/dashboard` redirects the SAED admin to `/app/users`.

## Dunis Admin (`dunis_admin`)

### Signup

Two creation paths exist:

1. Use hidden backend endpoint `POST /_sys/ops/`, with `ADMIN_SIGNUP_SECRET` and `role: dunis_admin`.
2. Use hidden frontend route `/x9k2m-admin`, which calls `POST /auth/admin-signup/` and always creates a Dunis admin.

Both paths create an email-verified account.

### Admin signup secret

- `ADMIN_SIGNUP_SECRET` is a backend environment variable, read from the backend deployment configuration (or `saed-backend/.env` for local development).
- It is not stored in a Django model and cannot be viewed, added, or changed through Django Admin at `/admin`.
- A system owner or deployment administrator must provision the value and share it with an authorized admin through a secure, out-of-band channel.
- For local testing, add `ADMIN_SIGNUP_SECRET=<long-random-value>` to `saed-backend/.env`, then restart the backend before using `/x9k2m-admin`.
- Do not commit the value, add a Django Admin screen that reveals it, or share it in source code, chat, or public documentation.

### Login and destination

- Sign in through the shared `/login` page.
- Successful login routes the Dunis admin to `/app/dunis-admin`.
- Opening `/admin/dashboard` also redirects the Dunis admin to `/app/dunis-admin`.

## Access Rules

- Public `/auth/signup/` accepts only the `corps_member` role.
- Trainer registration uses `/auth/trainer-signup/`.
- Admin user creation via `POST /manage/users/` is disabled (returns 405). Trainers must register through the public signup form.
- Unverified accounts cannot log in; they are directed to the verification/resend flow.
- Login determines access from the role stored in the backend profile. It does not accept a user-selected role as authorization.
- Password reset is a 3-step flow: (1) `POST /auth/forgot-password/` sends a 6-digit code to email and returns a token, (2) `POST /auth/verify-reset-code/` verifies the code, (3) `POST /auth/reset-password/` sets the new password using email + token + code + password.
- Fast track videos response includes `completedLessonIds` — an array of lesson IDs the enrolled student has already completed.
- SAED admins cannot activate/deactivate accounts (returns 403). Only Dunis admins can perform account lifecycle actions.
- Complaint forms (`/saed-question`, `/dunis-complaint`) require authentication; unauthenticated visitors are redirected to `/login`.
- Complaint submissions route to the appropriate admin role based on the `recipient` field. SAED questions go to SAED admins; Dunis complaints go to Dunis admins. Omitting the recipient sends to all admins.
- SAED and Dunis admins can access user-management functions. SAED handles trainer approval; Dunis handles trainer payment verification and the Dunis admin area.
- Enrollment status updates through `ManageApplicationDetailView` map UI labels to model values: `"approved"` → `"confirmed"`, `"declined"` → `"rejected"`, `"completed"` → `"completed"`.
- Admin course creation via `POST /manage/programs/` accepts a `trainerId` field to assign the course to a specific trainer. Omitting it assigns the course to the creating admin.
- Attempts to open a route not permitted for the current role redirect the user to that role's home destination.
- Logging out from the application clears the session and redirects to the shared `/login` page.

## Unified Program/Course Model

The system uses a single **Course** model as the unified training entity. The old `Program` and `Application` models have been removed. What was previously called a "Program" in the UI is now a Course record viewed through the `/programs/` endpoint.

### Key design decisions

- **Course** is the only training entity. Trainers create and manage courses via `/app/course-management`.
- `/programs/` and `/manage/programs/` are adapter endpoints that return Course objects in a program-shaped payload — the frontend sees no difference.
- `/applications/` and `/manage/applications/` return `CourseEnrollment` objects in an application-shaped payload.
- Corps members enroll directly in courses — there is no separate application/approval gate.
- Payment is required at enrollment time for priced courses.
- Admins oversee all courses (restrict/unrestrict); trainers manage only their own.

### Data model

| Model | Purpose |
|-------|---------|
| `Course` | Unified training entity (title, category, description, duration, capacity, trainer, location, price, start/end dates, restricted flag) |
| `CourseEnrollment` | Links a corps member to a course with status (`confirmed` after free enrollment or paid verification), payment reference, and refund tracking |
| `LessonProgress` | Tracks which lessons a student has completed (student, lesson, completed_at) |
| `Notification` | System notifications (no longer has a program FK) |

The `Program` and `Application` models no longer exist in the database.

## Functions Available by Authorization Level

### All authenticated users

- View their dashboard and profile.
- Update their profile.
- View notifications; mark one or all notifications as read.
- View course details.
- Mark lessons as completed and track course progress.
- Submit a complaint (routes to SAED or Dunis admin based on recipient).
- Initiate and verify course payments where applicable.
- Log out and use the password-reset flow.

### Corper

- Browse SAED programs (courses listed through the programs page).
- Enroll in courses directly (payment required for priced courses). Free courses are confirmed immediately; paid courses are confirmed after Paystack verification.
- View enrollment status and history.
- Browse available, approved trainers and view trainer details.
- Select trainers and send trainer-connection requests.
- View current trainer connections.
- Access Fast Track courses, their videos, and mark lessons as completed.
- View course progress (total lessons, completed lessons, percentage).

### Trainer

- Create, view, update, and delete their own courses (also shown as "programs" in the programs listing).
- View course enrollees and track student progress.
- View their connected corpers and each connected corper's profile.
- Approve or reject connection requests from corpers.
- View available programs.
- If granted `canUploadFastTrack` by Dunis Admin, create, update, and delete Fast Track videos and fetch video durations.

> Trainer access is conditional: the backend requires the trainer to be authorized, paid, and payment-verified for protected trainer actions. The frontend also treats an unauthorized or inactive trainer as inactive. Enrollment is auto-confirmed — trainers do not need to approve or reject enrollment requests.

### SAED Admin

- View the administrative dashboard and manage the non-hidden user list.
- View and update user records, including trainer approval/decline status, account activation, roles limited to corper/trainer, and trainer capabilities.
- View, create, update, and remove courses (also shown as "programs" in the programs listing).
- Restrict and unrestrict courses.
- View and manage enrollments (shown as "applications" in the enrollment management area — simplified to Student, Course, Progress columns).
- View pending course refunds and process or reject refunds.
- Cannot view users restricted by a Dunis Admin.

### Dunis Admin

- Has the shared admin capabilities: user management, course management, enrollment management, and refund processing.
- View all trainers and the trainer-payment queue.
- Confirm trainer payments, which records payment verification and enables paid status for an authorized trainer.
- Enable or disable a trainer's Fast Track upload capability.
- Restrict or remove user access where the interface permits; restrictions made by Dunis Admin are hidden from SAED Admin's user list.
- Access the dedicated `/app/dunis-admin` payments and Fast Track administration area.

## Frontend Routes

### Public

| Path | Component | Notes |
|------|-----------|-------|
| `/programs` | Programs | Browse all active courses |
| `/programs/:id` | ProgramDetail | Read-only course detail view |

### Corps Member (authenticated)

| Path | Component | Notes |
|------|-----------|-------|
| `/app` | Dashboard | Stats: enrollments, pending, approved, connections |
| `/app/programs` | Programs | Browse courses |
| `/app/programs/:id` | ProgramDetail | Course detail (read-only) |
| `/app/applications` | Applications | My Enrollments — tracks enrollment status |
| `/app/my-trainers` | MyTrainers | Browse and connect with trainers |
| `/app/my-courses` | MyCourses | Enrolled courses |
| `/app/trainee-fast-track` | TraineeFastTrack | Fast Track videos with lesson completion tracking |
| `/app/payment/verify` | CoursePaymentCallback | Payment verification |

### Trainer (authenticated)

| Path | Component | Notes |
|------|-----------|-------|
| `/app` | Dashboard | Stats: courses, corpers, programs |
| `/app/course-management` | CourseManagement | Create/edit/delete own courses |
| `/app/my-corpers` | MyCorpers | Connected corps members |
| `/app/manage-applications` | ManageApplications | Enrollments — view student progress |
| `/app/fast-track-videos` | FastTrackVideos | Upload Fast Track content (if enabled) |

### Admin (SAED/Dunis)

| Path | Component | Notes |
|------|-----------|-------|
| `/app` | Dashboard | Stats: trainers, corpers, connections |
| `/app/users` | ManageUsers | Trainer management |
| `/app/admin-courses` | AdminCourses | All courses — restrict/unrestrict |
| `/app/program-editor` | ProgramEditor | Course CRUD (create/edit/delete courses) |
| `/app/manage-applications` | ManageApplications | Enrollments — view student progress |
| `/app/admin-refunds` | AdminRefunds | Refund processing |
| `/app/dunis-admin` | DunisAdmin | Payments & Fast Track (Dunis only) |

## Backend API Endpoints

### Auth

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/auth/signup/` | POST | Corps member registration |
| `/api/auth/trainer-signup/` | POST | Trainer registration |
| `/api/auth/admin-signup/` | POST | Admin signup (requires secret) |
| `/api/auth/login/` | POST | Login (returns session cookie) |
| `/api/auth/logout/` | POST | Logout |
| `/api/auth/forgot-password/` | POST | Step 1: Send 6-digit reset code to email, return token |
| `/api/auth/verify-reset-code/` | POST | Step 2: Verify the 6-digit reset code |
| `/api/auth/reset-password/` | POST | Step 3: Set new password (email + token + code + password) |
| `/api/auth/verify-email/` | POST | Verify email address |
| `/api/auth/resend-verification/` | POST | Resend verification email |

### Programs (unified Course endpoints)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/programs/` | GET | Public listing — returns courses as programs |
| `/api/programs/:id/` | GET | Single program detail (Course object) |
| `/api/manage/programs/` | GET | Trainer/admin — their courses as programs |
| `/api/manage/programs/` | POST | Admin/trainer — create a new course (admin can send `trainerId` to assign to a specific trainer) |
| `/api/manage/programs/:id/` | PATCH | Trainer/admin — update course (admin can reassign via `trainerId`) |
| `/api/manage/programs/:id/restrict/` | POST | Admin — restrict a course |
| `/api/manage/programs/:id/unrestrict/` | POST | Admin — unrestrict a course |

### Applications (unified CourseEnrollment endpoints)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/applications/` | GET | Corps member — their enrollments |
| `/api/applications/create/` | POST | Corps member — enroll in a course |
| `/api/manage/applications/` | GET | Staff — all enrollments |
| `/api/manage/applications/:id/` | PATCH | Staff — update enrollment status (`approved`→`confirmed`, `declined`→`rejected`, `completed`→`completed`) |

### Courses

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/courses/` | GET | Public course listing |
| `/api/courses/:id/` | GET | Single course with trainer and enrolled count |
| `/api/courses/pay/` | POST | Initiate course payment |
| `/api/manage/courses/` | GET | Trainer — their courses |
| `/api/manage/courses/` | POST | Trainer — create course |
| `/api/manage/courses/:id/` | PATCH | Trainer — update course |
| `/api/manage/courses/:id/` | DELETE | Trainer — delete course |
| `/api/manage/courses/:id/restrict/` | POST | Admin — restrict course |
| `/api/manage/courses/:id/unrestrict/` | POST | Admin — unrestrict course |
| `/api/admin/courses/` | GET | Admin — all courses |

### Other

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/dashboard/` | GET | Dashboard stats and summary data |
| `/api/notifications/` | GET | User notifications |
| `/api/notifications/:id/read/` | POST | Mark notification read |
| `/api/notifications/read-all/` | POST | Mark all read |
| `/api/courses/pay/` | POST | Initiate course payment (returns Paystack authorization_url) |
| `/api/courses/pay/verify/` | POST | Verify course payment with Paystack |
| `/api/courses/:id/enrollment-status/` | GET | Check enrollment status for a course |
| `/api/fast-track-videos/:courseId/` | GET | Fast track videos for a course (includes completedLessonIds for enrolled students) |
| `/api/courses/:id/progress/` | GET | Authenticated — get course progress (totalLessons, completedLessons, percentage) |
| `/api/courses/:id/lessons/:lessonId/complete/` | POST | Authenticated — mark a lesson as completed |
| `/api/admin/refunds/pending/` | GET | Admin — pending refund requests |
| `/api/admin/refunds/:id/process/` | POST | Admin — process refund via Paystack |
| `/api/admin/refunds/:id/reject/` | POST | Admin — reject refund request |
| `/api/webhooks/paystack/` | POST | Paystack webhook (HMAC SHA512) |
| `/api/submit-complaint/` | POST | Submit a complaint (SAED or Dunis) |

## Implementation References

- Backend authentication and signup: `saed-backend/saed/views/auth.py`
- Backend user management (admin create disabled): `saed-backend/saed/views/users.py`
- Backend complaint routing (recipient validation): `saed-backend/saed/views/complaints.py`
- Backend program/course adapter: `saed-backend/saed/views/programs.py`
- Backend course CRUD and admin views: `saed-backend/saed/views/courses.py`
- Backend enrollment management: `saed-backend/saed/views/programs.py` (ManageApplicationsView, ManageApplicationDetailView)
- Backend payment init, verify, webhook, refunds: `saed-backend/saed/views/payments.py`
- Backend lesson progress tracking: `saed-backend/saed/views/courses.py` (CourseProgressView, LessonCompleteView)
- Data models (Course, CourseEnrollment, LessonProgress, Notification, Complaint): `saed-backend/saed/models.py`
- Fast track videos with completion tracking: `saed-backend/saed/views/fast_track.py`
- Frontend route protection and role destinations: `saed-frontend/src/index.js`
- Application-shell logout redirect and inactive-trainer redirect: `saed-frontend/src/components/layout/AppShell.jsx`
- Login behavior: `saed-frontend/src/pages/auth/Login.jsx`
- Password reset (3-step flow with 6-digit code boxes): `saed-frontend/src/pages/auth/ForgotPassword.jsx`
- Course payment callback: `saed-frontend/src/pages/corper/CoursePaymentCallback.jsx`
- Trainer course management: `saed-frontend/src/pages/trainer/CourseManagement.jsx`
- Trainee fast track with lesson completion: `saed-frontend/src/pages/corper/TraineeFastTrack.jsx`
- Admin course management: `saed-frontend/src/pages/admin/AdminCourses.jsx`
- Admin program editor (CRUD): `saed-frontend/src/pages/admin/ProgramEditor.jsx`
- SAED admin signup: `saed-frontend/src/pages/auth/AdminSignup.jsx` (`/x9k2m-admin`)
- Dunis admin signup: `saed-frontend/src/pages/auth/DunisAdminSignup.jsx` (`/d9x7k-admin`)
- Trainer access requirements: `saed-backend/saed/views/base.py` (HasTrainerRole, HasRole)
