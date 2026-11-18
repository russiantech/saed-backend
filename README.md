# SAED Learning Platform — Frontend

**React 19 + Vite** single-page application for the Skills Acquisition & Entrepreneurship Development (SAED) platform used by NYSC corps members, trainers, and administrators.

**Version:** 2.5.0  
**Stack:** React 19, Vite 8, React Router 7, Vitest, ESLint 10, pdf.js (in-app documents)

---

## Overview

The frontend delivers **two professionally separated experiences** in one application:

| Track        | Entry points                          | Behaviour |
|--------------|---------------------------------------|-----------|
| **In-Camp**  | `/signup/in-camp`, public “In-Camp” link | Stream-based. No LGA/PPA. Dashboard and access expire after the stream ends. |
| **Post-Camp**| `/signup/post-camp`                   | Ongoing. Full location fields used for discovery. |

A chooser lives at `/signup`. Sign-up components are shared where it makes sense, but the two tracks never mix data, navigation or course catalogues. Crossing tracks is blocked by the API (`403`).

Admins see a grouped sidebar: **In-Camp SAED / Post-Camp SAED / Platform**.

---

## Key user journeys

### Corps member (In-Camp)
1. Public site → **In-Camp** → sign-up (choose open stream + optional camp + skills).
2. Dashboard shows stream window and days remaining.
3. Enrol in In-Camp courses → learn (video / PDF / text) entirely inside the app.
4. After the stream ends the dashboard is replaced by an “ended” page; profile and notifications remain available.

### Corps member (Post-Camp)
1. Sign-up with state, LGA, PPA and skill interests.
2. Browse the full catalogue, enrol, connect with trainers, pay for premium lessons (Paystack or bank transfer).

### Trainer
- **In-Camp trainers** are created by SAED Admin and receive an invite email. They set their own password, propose courses for the stream, and manage lessons once approved.
- **Post-Camp trainers** self-register, pay the activation fee, and manage their own catalogue and earnings.

### SAED Admin
- Streams (create / edit, up to 6 per year)
- In-Camp trainers (create, invite, edit, deactivate, reactivate)
- Proposals (approve / decline)
- Reports (filter by stream / year, CSV export)
- Users, courses, camps, enrolments

### Dunis Admin
Everything above plus **Payments & Fees** (video fee, platform share, mismatch review, etc.).

---

## Repository layout

```
frontend/
├── public/                 # logo, favicons
├── src/
│   ├── components/         # BrandLogo, DocumentViewer, forms, layout, …
│   ├── pages/              # route-level screens (auth, dashboards, admin, …)
│   ├── api/                # thin fetch wrappers + CSRF handling
│   ├── hooks/
│   ├── styles/             # forms.css + global design tokens
│   ├── __tests__/
│   └── App.jsx / main.jsx
├── index.html
├── vite.config.js
├── package.json
└── .env.example
```

---

## Quick start (local)

**Requirements:** Node.js **≥ 22.13** (required by pdf.js; Node 20 is end-of-life).

```bash
cd frontend
cp .env.example .env
npm install                 # 0 deprecated packages, 0 audit findings
npm run dev                 # or: npm start  → http://localhost:3002
```

The Vite dev server proxies `/api` and media requests to the backend (default `http://127.0.0.1:8002`).

### Environment

| Variable            | Purpose                                      |
|---------------------|----------------------------------------------|
| `VITE_API_URL`      | API base (usually `/api` behind the proxy)   |
| `VITE_BACKEND_URL`  | Absolute backend origin when needed          |
| `VITE_LOGO_URL`     | Optional override for the brand logo         |

Production build:

```bash
npm run build               # output in frontend/build (or dist)
npm test && npm run lint
```

---

## Design & UX principles

- **In-app only** — lesson documents and partnership letters open inside the page (pdf.js canvas, images, text). No download / new-tab / print actions.
- **Consistent forms** — shared control system (`forms.css`): 46 px fields, 12 px radius, 44 px touch targets, no iOS zoom.
- **Role-specific sidebars** — exactly the items each role needs; legacy URLs redirect.
- **Brand** — NYSC emblem in sidebar, public nav and every auth page. Auth logos link home.
- **Responsive** — single-column forms on small screens; clear empty states (“nothing listed under this skill set”, “stream has ended”, etc.).

---

## Tracks & routing (v2.5)

| Path                        | Purpose |
|-----------------------------|---------|
| `/`                         | Public landing (Explore → In-Camp) |
| `/signup`                   | Track chooser |
| `/signup/in-camp`           | In-Camp registration (stream required) |
| `/signup/post-camp`         | Post-Camp registration |
| `/app/...`                  | Authenticated area (dashboard, courses, admin, …) |
| `/app/streams`              | SAED Admin — manage streams |
| `/app/incamp-trainers`      | SAED Admin — In-Camp trainer CRUD |
| `/app/proposals`            | SAED Admin — review trainer proposals |
| `/app/reports`              | Stream reports + CSV |
| `/forgot`                   | Password reset (also used by trainer invite links) |

Expired In-Camp users still reach profile and notifications; other routes show the ended state or receive `403` from the API.

---

## Integration with the backend

- Session cookies + CSRF token (`GET /api/csrf/`) for all mutating requests.
- The API returns `link` on notifications so the UI can deep-link.
- Course IDs are UUIDs (legacy integer URLs still resolve on the backend).
- Error shape: `{ "error": "…" }` (validation may add `fields`).

See the backend README and `docs/API.md` for the full contract.

---

## Testing

```bash
npm run lint
npm test
npm run build
```

Frontend tests cover track chooser, track-specific sign-up, navigation per track, expired-stream page, document viewer behaviour, and form validation.

---

## Related documentation

- [Backend README](../backend/README.md)
- [API reference](../docs/API.md)
- [CHANGES.md](../docs/CHANGES.md) — full version history
- [WALKTHROUGHS.md](../docs/WALKTHROUGHS.md) — non-technical user journeys
- [IN_CAMP_SAED.md](../docs/IN_CAMP_SAED.md) — what the In-Camp / Streams update delivered

---

**License:** Proprietary  
**Maintainers:** SAED / Dunis platform team
