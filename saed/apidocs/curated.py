"""Hand-written documentation layered on top of the introspected OpenAPI spec."""
import re

API_VERSION = "2.4.0"

DESCRIPTION = """\
The SAED API powers the Skills Acquisition & Entrepreneurship Development platform for NYSC corps members,
their trainers and SAED / Dunis administrators.

## Authentication
Session-cookie authentication. `POST /auth/login/` sets the session cookie. **All unsafe requests
(POST/PUT/PATCH/DELETE) must send the `X-CSRFToken` header** — fetch the token from `GET /csrf/`.
In Swagger UI the header is added automatically.

## Roles
`corps_member`, `trainer`, `saed_admin`, `dunis_admin`. Each operation lists the roles allowed to call it.

## Errors
Failures return JSON `{"error": "<human readable message>"}` (validation errors may add `fields`).
Authentication throttling returns **429** with a `Retry-After` header.

## Payments
Paystack amounts are in **kobo** (`amountKobo`) and always verified server-side against the amount the
server requested. Never trust a browser callback — call `POST /payments/verify/` or rely on the signed
webhook (`POST /webhooks/paystack/`, `x-paystack-signature` HMAC-SHA512, idempotent).

## Media
Lesson videos/documents are private. They are streamed by `GET /lessons/{lesson_id}/media/{kind}/` after an
access check, with HTTP `Range` support. They are never exposed via a public URL.

## Pagination
List endpoints that accept `page` / `pageSize` return `{"results": [...], "count": n, "page": p, "pageSize": s}`.
"""

TAGS = [
    ("System", "Health probes and CSRF bootstrap."),
    ("Auth", "Sign-up, login, verification codes and password reset."),
    ("Profile", "The signed-in user's profile."),
    ("Dashboard", "Role-specific dashboard data."),
    ("Programs", "SAED programs and applications."),
    ("Trainers", "Trainer discovery, connections and earnings."),
    ("Courses", "Courses, enrolment and progress."),
    ("Lessons", "Lesson content, media, access and uploads."),
    ("Payments", "Paystack initialisation, verification, ledger and webhook."),
    ("Dunis Admin", "Platform finance & settings (Dunis administrators)."),
    ("Admin", "SAED administration: users, programs, refunds, camps, sessions."),
    ("Notifications", "In-app notifications."),
    ("Banks", "Paystack bank list and account resolution."),
    ("Misc", "Complaints and other endpoints."),
]

_TAG_RULES = [
    (r"^(health|csrf|auth/me)", "System"),
    (r"^auth/update-profile", "Profile"),
    (r"^auth/", "Auth"),
    (r"^dashboard", "Dashboard"),
    (r"^(programs|applications|manage/programs|manage/applications)", "Programs"),
    (r"^(trainers|my-trainers|connect|connections|trainer/)", "Trainers"),
    (r"^manage/lessons|^lessons/|^media/|^manage/access-requests", "Lessons"),
    (r"^(courses|my-courses|manage/courses|admin/courses|incamp/)", "Courses"),
    (r"^(payments|paystack|webhooks)", "Payments"),
    (r"^dunis/|^admin/platform-settings", "Dunis Admin"),
    (r"^(manage/users|manage/orientation|manage/training|admin/|orientation-camps)", "Admin"),
    (r"^notifications", "Notifications"),
    (r"^banks", "Banks"),
]


def tag_for(route):
    for rx, tag in _TAG_RULES:
        if re.search(rx, route):
            return tag
    return "Misc"


def operation_id(method, route):
    core = re.sub(r"<(?:\w+:)?(\w+)>", r"by_\1", route).strip("/")
    core = re.sub(r"[^A-Za-z0-9]+", "_", core).strip("_")
    return f"{method}_{core}"


FUNCTION_VIEW_METHODS = {
    "health/": ("get",), "health/ready/": ("get",), "csrf/": ("get",), "auth/me/": ("get",),
    "webhooks/paystack/": ("post",),
}

PATH_PARAMS = {
    "course_id": "Course UUID.", "lesson_id": "Lesson id.", "kind": "`video`, `document` or `thumbnail`.",
    "reference": "Payment reference (e.g. `SAED-...`).", "program_id": "Program id.",
    "trainer_id": "Trainer user id.", "corper_id": "Corps member user id.", "user_id": "User id.",
    "connection_id": "Connection id.", "application_id": "Application id.", "enrollment_id": "Enrollment id.",
    "notification_id": "Notification id.", "camp_id": "Orientation camp id.", "session_id": "Training session id.",
}

QUERY_PARAMS = {
    "page": "1-based page number.", "pageSize": "Items per page.", "q": "Free-text search.",
    "search": "Free-text search.", "status": "Filter by status.", "role": "Filter by role.",
    "category": "Filter by category.", "state": "Filter by state.", "lga": "Filter by LGA.",
    "type": "Filter by type.", "course": "Filter by course id.", "program": "Filter by program id.",
}

FIELDS = {
    "email": "Email address.", "password": "Account password.", "username": "Username.",
    "reference": "Payment reference.", "lessonId": "Lesson id.", "courseId": "Course UUID.",
    "note": "Free-text note.", "code": "Verification code.", "fullName": "Full name.",
    "title": "Title.", "description": "Description.", "price": "Price in NGN (0 = free).",
    "isPremium": "Whether the lesson requires payment.",
}

SCHEMAS = {
    "Error": {"type": "object", "required": ["error"], "properties": {
        "error": {"type": "string", "examples": ["Lesson not found."]},
        "fields": {"type": "object", "additionalProperties": {"type": "string"}}}},
    "Pagination": {"type": "object", "properties": {
        "count": {"type": "integer"}, "page": {"type": "integer"}, "pageSize": {"type": "integer"}}},
    "User": {"type": "object", "properties": {
        "id": {"type": "integer"}, "username": {"type": "string"}, "email": {"type": "string", "format": "email"},
        "fullName": {"type": "string"}, "role": {"enum": ["corps_member", "trainer", "saed_admin", "dunis_admin"]},
        "phone": {"type": "string"}, "stateOfDeployment": {"type": "string"}, "lgaOfDeployment": {"type": "string"},
        "nyscStateCode": {"type": "string"}, "skillInterests": {"type": "array", "items": {"type": "string"}},
        "specialization": {"type": "string"}, "yearsExperience": {"type": "integer"}, "bio": {"type": "string"},
        "hasPaid": {"type": "boolean"}, "isActive": {"type": "boolean"}}},
    "Course": {"type": "object", "properties": {
        "id": {"type": "string", "format": "uuid"}, "title": {"type": "string"}, "description": {"type": "string"},
        "category": {"type": "string"}, "categoryLabel": {"type": "string"}, "trainerId": {"type": "integer"},
        "trainerName": {"type": "string"}, "durationWeeks": {"type": "integer"}, "isPublished": {"type": "boolean"},
        "partnerLgas": {"type": "array", "items": {"type": "string"}}}},
    "Lesson": {"type": "object", "properties": {
        "id": {"type": "integer"}, "courseId": {"type": "string", "format": "uuid"}, "title": {"type": "string"},
        "description": {"type": "string"}, "order": {"type": "integer"},
        "contentType": {"enum": ["video", "document", "text"]}, "durationSeconds": {"type": "integer"},
        "price": {"type": "number", "description": "NGN; 0 means free."},
        "requiresPayment": {"type": "boolean"}, "hasPaid": {"type": "boolean"},
        "isLocked": {"type": "boolean"}, "isAuthorized": {"type": "boolean"}, "isPublished": {"type": "boolean"}}},
    "PaymentInit": {"type": "object", "properties": {
        "ok": {"type": "boolean"}, "reference": {"type": "string"}, "authorizationUrl": {"type": "string", "format": "uri"},
        "accessCode": {"type": "string"}, "amountKobo": {"type": "integer"}, "amount": {"type": "number"}}},
    "Payment": {"type": "object", "properties": {
        "reference": {"type": "string"}, "type": {"enum": ["trainer_activation", "video_upload", "lesson_access"]},
        "status": {"enum": ["pending", "success", "failed", "abandoned", "amount_mismatch", "refunded"]},
        "amount": {"type": "number"}, "amountKobo": {"type": "integer"}, "channel": {"type": "string"},
        "createdAt": {"type": "string", "format": "date-time"}}},
    "VerifyResult": {"type": "object", "properties": {
        "ok": {"type": "boolean"}, "status": {"type": "string"}, "message": {"type": "string"},
        "payment": {"$ref": "#/components/schemas/Payment"}}},
    "PlatformSettings": {"type": "object", "properties": {
        "videoUploadFee": {"type": "number", "description": "NGN, default 2000"},
        "videoUploadFeeEnabled": {"type": "boolean"}, "trainerActivationFee": {"type": "number"}}},
    "Health": {"type": "object", "properties": {"status": {"type": "string", "examples": ["ok"]}}},
}


def _err(desc):
    return {"description": desc, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}


RESPONSES = {
    "BadRequest": _err("Validation failed or the request is not allowed in the current state."),
    "Unauthorized": _err("Not signed in."),
    "Forbidden": _err("Signed in but not allowed (wrong role, missing CSRF token, or no access to this resource)."),
    "NotFound": _err("Resource not found (or not visible to the caller)."),
    "TooManyRequests": {"description": "Rate limit exceeded; see the `Retry-After` header.",
                        "headers": {"Retry-After": {"schema": {"type": "integer"}}},
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
}


def _ref(name, desc="Success."):
    return {"description": desc, "content": {"application/json": {"schema": {"$ref": f"#/components/schemas/{name}"}}}}


def _body(props, required=()):
    return {"type": "object", "required": list(required), "properties": props}


S = {"type": "string"}
OPERATIONS = {
    "GET /health/": {"summary": "Liveness probe", "description": "Returns 200 while the process is up. Does not touch the database.", "response": _ref("Health")},
    "GET /health/ready/": {"summary": "Readiness probe", "description": "Checks the database (`SELECT 1`) and that private media storage is writable. Returns **503** when not ready.",
                           "extra_responses": {"503": {"description": "Not ready."}}},
    "GET /csrf/": {"summary": "Get a CSRF token", "description": "Sets the `csrftoken` cookie and returns the token to send as `X-CSRFToken`.",
                   "response": {"description": "Token.", "content": {"application/json": {"schema": _body({"csrfToken": S})}}}},
    "GET /auth/me/": {"summary": "Current user", "description": "Returns `{\"user\": null}` when signed out.",
                      "response": {"description": "Current user.", "content": {"application/json": {"schema": _body({"user": {"anyOf": [{"$ref": "#/components/schemas/User"}, {"type": "null"}]}})}}}},
    "POST /auth/login/": {"summary": "Sign in", "description": "Creates a session. Throttled (scope `auth`).",
                          "body": _body({"email": S, "username": S, "password": S}, ["password"])},
    "POST /auth/logout/": {"summary": "Sign out"},
    "POST /auth/signup/": {"summary": "Register a corps member", "created": True},
    "POST /auth/trainer-signup/": {"summary": "Register a trainer", "created": True},
    "POST /auth/admin-signup/": {"summary": "Register a SAED admin (needs the admin signup code)"},
    "POST /auth/send-code/": {"summary": "Send an email verification code"},
    "POST /auth/verify-code/": {"summary": "Verify an email verification code"},
    "POST /auth/forgot-password/": {"summary": "Request a password-reset code"},
    "POST /auth/verify-reset-code/": {"summary": "Verify a password-reset code"},
    "POST /auth/reset-password/": {"summary": "Set a new password using a verified code"},
    "PATCH /auth/update-profile/": {"summary": "Update my profile"},
    "POST /courses/{course_id}/enroll/": {"summary": "Enrol in a course (one step)", "description": "Enrols the corps member and auto-connects them to the course trainer. Idempotent."},
    "POST /courses/enroll/": {"summary": "Enrol in a course (courseId in body)"},
    "GET /lessons/{lesson_id}/": {"summary": "View a lesson", "description": "Returns the lesson plus `isAuthorized`; locked premium lessons omit media URLs."},
    "GET /lessons/{lesson_id}/media/{kind}/": {"summary": "Stream private lesson media",
        "description": "Access-checked streaming with `Range` support. `Cache-Control: private, no-store`.",
        "response": {"description": "Media bytes (200 full / 206 partial).", "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}},
        "extra_responses": {"206": {"description": "Partial content."}, "416": {"description": "Range not satisfiable."}}},
    "POST /manage/lessons/{lesson_id}/upload/": {"summary": "Upload lesson media", "description": "Multipart. Video uploads require the video upload fee to be paid first when `feeApplies` is true (HTTP 402-style error with `paymentRequired`)."},
    "POST /payments/trainer-activation/": {"summary": "Start trainer activation payment", "response": _ref("PaymentInit"), "body_required": False},
    "POST /payments/video-upload/": {"summary": "Start the video-upload fee payment for a lesson", "description": "Fee is configurable by Dunis Admin (default ₦2,000).",
        "body": _body({"lessonId": {"type": "integer"}}, ["lessonId"]), "response": _ref("PaymentInit")},
    "POST /payments/lesson/": {"summary": "Start payment for a premium lesson",
        "body": _body({"lessonId": {"type": "integer"}}, ["lessonId"]), "response": _ref("PaymentInit")},
    "POST /payments/verify/": {"summary": "Verify a payment server-side",
        "description": "Calls Paystack, compares the *requested* amount strictly and updates the ledger. Safe to call repeatedly.",
        "body": _body({"reference": S}, ["reference"]), "response": _ref("VerifyResult")},
    "GET /payments/mine/": {"summary": "My payments", "response": {"description": "Payments.", "content": {"application/json": {"schema": _body({"results": {"type": "array", "items": {"$ref": "#/components/schemas/Payment"}}})}}}},
    "GET /payments/config/": {"summary": "Public payment configuration (fees, Paystack public key)"},
    "GET /payments/{reference}/": {"summary": "Payment detail", "response": _ref("Payment")},
    "POST /webhooks/paystack/": {"summary": "Paystack webhook",
        "description": "Verifies `x-paystack-signature` (HMAC-SHA512 of the raw body with the secret key). Events are stored by id so replays are no-ops. Always answers 200 for valid, already-processed events.",
        "body": {"type": "object", "additionalProperties": True}},
    "GET /admin/platform-settings/": {"summary": "Read platform settings", "response": _ref("PlatformSettings")},
    "PATCH /admin/platform-settings/": {"summary": "Update platform settings (Dunis Admin only)", "description": "Includes the video upload fee and its on/off switch.", "response": _ref("PlatformSettings")},
    "POST /dunis/confirm-payment/": {"summary": "Confirm a manual bank-transfer payment"},
    "POST /dunis/payments/{reference}/resolve/": {"summary": "Resolve a stuck or mismatched payment"},
    "GET /courses/": {"summary": "List published courses"},
    "GET /courses/{course_id}/": {"summary": "Course detail with lessons"},
    "GET /banks/": {"summary": "List Paystack banks"},
    "POST /banks/resolve/": {"summary": "Resolve a bank account name"},
}
