# Healthcare Admin AI — Hackathon Build

Upload a Prior Authorization or Insurance Claim form → AI extracts the fields
and flags anything missing/uncertain → you review & correct → it drafts the
outgoing paperwork. Human always reviews before anything is submitted.

## 1. Setup (5 minutes)

```bash
cd backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

export GEMINI_API_KEY=AI...    # Windows (PowerShell): $env:GEMINI_API_KEY="AI..."
# Get a free key (no card required) at https://aistudio.google.com/apikey
```

## 2. Run the backend

```bash
uvicorn main:app --reload --port 8000
```

Check it's alive: open http://localhost:8000/health — should return `{"status":"ok"}`.

## 3. Run the frontend

No build step. Two frontend pages are included:

- `frontend/dashboard.html` — the main demo screen: stat cards, drag-and-drop
  extraction panel with a live preview, and a Recent Records table backed by
  a local SQLite database (`backend/records.db`, created automatically).
  **Use this one for your pitch demo.**
- `frontend/index.html` — the earlier simple single-flow version, kept as a
  fallback if you want a leaner UI.

Open in a browser via `Ctrl+O` / right-click → "Open with" your browser
(not VS Code). Both talk to the backend at `localhost:8000`.

## 4. Get sample test forms

You need a handful of realistic-looking Prior Auth and Insurance Claim
forms to test with and to demo. Options, fastest first:

- Search "prior authorization form pdf sample" / "CMS-1500 claim form
  sample" — CMS-1500 and UB-04 are standard public claim form templates,
  and many payers (e.g. UnitedHealthcare, Aetna) publish blank sample
  prior-auth PDFs you can fill in with fake data.
- Fill 2–3 with clean data, 1–2 with messy/handwritten-looking data
  (print, scribble, rescan or photograph) — the messy one is what makes
  your live demo memorable.
- Make sure at least one sample is missing a required field on purpose,
  so you can show off the "flag missing fields" behavior live.

**Do not use any real patient data** — synthetic/fake data only, this
matters even for a demo.

## 5. Team split from here

- **Backend owner**: test `/extract` against all your sample forms early,
  tune the prompt in `extractor.py` if a field is consistently
  mis-extracted (add a one-line hint to that field's description in
  `schemas.py`).
- **Frontend owner**: polish the review screen, loading states, and the
  missing-field highlighting — this is what judges actually watch.
- **Pitch owner**: build the "time saved" stat and deck while the others
  are still building; don't leave this to the last hour.

## How it works

```
Upload (PDF/PNG/JPG)
   → POST /extract  → Claude reads the doc directly (no separate OCR step)
                        → returns JSON: {field: {value, confidence}}
   → Frontend shows editable fields, red-flags anything "missing"
   → You correct/confirm
   → POST /generate → fills the outgoing document template
   → Download as .txt (swap in python-docx later for a nicer output if time allows)
```

Adding a third form type later: add one entry to `FORM_SCHEMAS` in
`schemas.py` and one branch in `generate_draft()` in `drafter.py` —
nothing else needs to change.

## If the live demo API call fails during judging

Have a recorded screen-capture of a full successful run ready as backup.
Record it once everything's working, well before your slot.
