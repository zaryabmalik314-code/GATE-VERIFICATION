# LGU Gate Verify

Checks a student's ID card at the gate and tells the guard whether they're
currently allowed on campus — rejecting **graduated** students and
**frozen-semester / dropped-out** students.

## How it works

1. Guard scans/photographs the student's ID card (webcam, phone, or any camera).
2. OCR (Tesseract) reads the **Roll No** and **Session** fields off the card.
3. **Check 1 — Graduated:** the Session field (e.g. `Fa-2025-29`) encodes the
   expected end year (2029). If the current year is past that, the student is
   marked **graduated** and denied — no manual list needed for this case.
4. **Check 2 — Frozen / Dropped:** the roll number is checked against a
   manually maintained list (uploaded as CSV, or added one-by-one in the admin
   page). If present, denied with the reason and note shown.
5. Otherwise: **Allowed**.

If OCR can't read the card clearly (bad lighting, glare, blur), the guard can
switch to the **"Type Roll No."** tab and enter it manually — this never
blocks the gate.

## Pages

- `/` — guard-facing scan/verify page
- `/admin` — upload the frozen/dropped CSV or manage entries one at a time
- `/health` — health check
- `/docs` — interactive API docs (FastAPI auto-generated)

## CSV format for the frozen/dropped list

```csv
roll_number,status,note
Fa-2022-BS CS-014,dropped,Left in 3rd semester
Fa-2023-BS SE-030,frozen,Medical leave
```

`status` must be `frozen` or `dropped`. Re-uploading updates existing entries
(matched by roll number), so you can just re-export and re-upload the whole
list whenever your teacher gives you an update — no need to track diffs.

## Local setup

```bash
# Tesseract must be installed as a system package (not pip)
# Ubuntu/Debian: sudo apt-get install tesseract-ocr
# Windows: https://github.com/UB-Mannheim/tesseract/wiki
# Mac: brew install tesseract

pip install -r requirements.txt
uvicorn app.main:app --reload
```

Then open `http://localhost:8000`.

## Deploying to Railway

1. Push this folder to a new GitHub repo.
2. Connect the repo in Railway — it will detect the `Dockerfile` automatically
   (Tesseract needs to be installed via `apt`, so this uses Docker rather than
   Railway's native Python buildpack, which can't install system packages).
3. No environment variables are required to get started.
4. **Important — persistent storage:** by default Railway's filesystem is
   ephemeral, meaning the frozen/dropped list (`app/data/status.db`) would be
   wiped on every redeploy. Before relying on this in production:
   - Add a **Railway Volume** mounted at `/app/app/data`, **or**
   - Swap `status_list.py` to use Postgres instead of SQLite (same pattern as
     your other Railway projects — you already have this working elsewhere).
   For a demo to your teacher, the SQLite version is fine as-is.

## Known limitations / next steps

- OCR accuracy depends on photo quality — test with a few real gate photos
  (different lighting, angles) before relying on this daily.
- The regex parser expects the card's current layout ("Roll No: ...",
  "Session: XX-YYYY-YY"). If LGU changes the card design, `app/ocr.py`'s
  patterns will need updating.
- `/admin` currently has no login — add basic auth or a password gate before
  giving guards/office staff the URL, since anyone with the link could edit
  the list.
- Session year assumes 2-digit end years share the century of the start year
  (`Fa-2025-29` → 2029). Fine for the foreseeable future; revisit after 2099.
