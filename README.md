# Chhabinathpur Durga Pooja Samiti

A portable, mobile-first React + FastAPI + MongoDB website for Chhabinathpur Durga Pooja Samiti, Jigna, Mirzapur. It is not tied to Emergent or any other hosting provider.

## What is included

- Traditional deep-red, antique-gold visual system with original SVG/CSS emblem and clearly-labelled illustration placeholders.
- Public pages for Home, About, Schedule, Maa Durga, Cultural Programs, Gallery, Donation, Committee, Village, Announcements and Contact.
- Live countdown to 11 October 2026, configurable Aarti times, QR sharing and UPI deep-link donation (`8172938399@ybl` by default).
- Donation submission with a clear non-confirmation warning, secure UTR validation, admin verification and sequential receipts such as `CDPS-2026-0001`.
- Private financial summary based only on verified donations and recorded expenses.
- Secure JWT-protected admin dashboard for announcements, schedule, programs, committee, gallery uploads, donations, expenses and site settings.
- Privacy-conscious visitor counter using a daily salted anonymous identifier; no fabricated numbers or raw IP storage.
- Responsive layout, keyboard-friendly controls, accessible labels, SEO metadata, sitemap and robots file.

## Architecture

```text
frontend/   React + Vite SPA (deploy to Vercel, Netlify, etc.)
backend/    FastAPI REST API (deploy to Render, Railway, etc.)
MongoDB     MongoDB Atlas or existing MongoDB deployment
```

The backend automatically uses temporary in-memory storage only for local development when `MONGO_URL` is empty and `ALLOW_MEMORY_STORE=true`. Set `ALLOW_MEMORY_STORE=false` in production so a missing database causes a safe startup failure.

## Run locally

1. Create `backend/.env` from `backend/.env.example`. Change `SECRET_KEY` and `ADMIN_PASSWORD`.
2. Optional but recommended: set `MONGO_URL` to a local MongoDB or MongoDB Atlas connection string.
3. In one terminal:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

4. In another terminal:

```powershell
cd frontend
Copy-Item .env.example .env
npm install
npm run dev
```

Open `http://localhost:5173`. The API docs are at `http://localhost:8000/docs` in non-production mode.

## First admin account

On the first backend startup, the API creates one administrator from `ADMIN_USERNAME` and `ADMIN_PASSWORD`. Set both values to unique, private credentials before deploying. There is deliberately no public signup endpoint.

## MongoDB collections

`admins`, `announcements`, `schedule`, `programs`, `gallery`, `committee`, `donations`, `expenses`, `visitors`, `counters`, and `site_settings`.

The `counters` collection atomically assigns receipt numbers. The `visitors` collection holds only a salted one-day anonymous fingerprint and day; it does not hold donor data or raw visitor IP addresses.

## Configure UPI and public settings

Sign in at `/admin/login`, then use **Site Settings** to update UPI ID, contact/WhatsApp number, address, venue, map URL, dates, Aarti times and footer. The donate screen generates a `upi://pay` URL and a QR code from the selected amount. It never claims payment success on app launch; donors submit a UTR and an administrator verifies it.

Never collect or store UPI PINs, card/ATM PINs, banking passwords or OTPs.

## Deploy frontend

### Vercel

- Import the repository and select `frontend` as the Root Directory.
- Build command: `npm run build`; output directory: `dist`.
- Add `VITE_API_BASE=https://YOUR-API.example/api` and `VITE_SITE_URL=https://YOUR-SITE.example`.
- `vercel.json` provides the SPA rewrite.

### Netlify

- Base directory: `frontend`; build command: `npm run build`; publish directory: `frontend/dist`.
- Add the same `VITE_*` variables. `public/_redirects` provides the SPA rewrite.

## Deploy backend

### Render

- Connect the repository and use the included `render.yaml`, or create a Python Web Service with root directory `backend`.
- Build: `pip install -r requirements.txt`.
- Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
- Add `MONGO_URL`, `SECRET_KEY`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, and `CORS_ORIGINS=https://YOUR-SITE.example`.
- Set `ALLOW_MEMORY_STORE=false`.

Railway uses the same install/start commands and environment variables.

## MongoDB Atlas

Create a database user with a strong password and a network rule appropriate to the deployment host. Put its connection string in `MONGO_URL`, for example:

```text
mongodb+srv://USER:PASSWORD@CLUSTER.mongodb.net/cdps?retryWrites=true&w=majority
```

URL-encode special characters in the password. Do not commit this value or any `.env` file.

## Production notes

- Local filesystem gallery uploads are appropriate for a single Render/Railway instance but may be ephemeral on some hosts. Before long-term use, swap the upload adapter for S3, Cloudinary or equivalent object storage while retaining the server-side MIME, signature and size checks.
- Update `frontend/public/sitemap.xml`, canonical URL and Open Graph URL from `example.org` to the final domain before launch.
- Add the real public Google Maps URL and official Puja images from the admin panel. The included art is explicitly illustrative, not a claim about Chhabinathpur photographs.
