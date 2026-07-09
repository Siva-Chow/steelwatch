# Steelwatch

A self-updating tracker for engineering roles (process, materials, R&D, development, quality)
across the European steel sector — Germany, Austria, Switzerland, Sweden, Luxembourg, France.

It pulls roles from company career-page feeds plus Indeed and Google Jobs, scores each one
against a metallurgy/continuous-casting profile, flags what's new, and shows it all on a dashboard
that lives at a web address you can bookmark. It refreshes itself once a day. No server, no cost
beyond a few cents of Apify credit.

---

## Go live — one-time setup (about 10 minutes, no coding)

### 1. Create the repository
1. Go to https://github.com/new
2. Repository name: **steelwatch** (or any name you like)
3. Description (optional): *Live steel & metallurgy engineering job tracker with fit scoring and application tracking*
4. Set it to **Public** (required for the free dashboard hosting)
5. Leave **"Add a README file", .gitignore, and license all UNCHECKED** — the repo must start empty so the upload is clean
6. Click **Create repository**

### 2. Upload the files
1. On the new repo page, click **uploading an existing file**
2. Drag in these files and folders from the package:
   `index.html`, `jobs.json`, `config.json`, `scraper.py`, `requirements.txt`, `README.md`, and the `data` folder
3. Click **Commit changes**
4. The workflow file must keep its folder path. Click **Add file → Create new file**, type this exact name:
   `.github/workflows/update.yml`
   then paste in the contents of that file from the package, and **Commit**.
   *(Typing the path with the slashes tells GitHub to create the folders for you.)*

### 3. Turn on the dashboard (GitHub Pages)
1. In the repo: **Settings → Pages**
2. Under **Build and deployment → Source**, choose **Deploy from a branch**
3. Branch: **main**, folder: **/ (root)** → **Save**
4. After a minute, your dashboard is live at:
   **https://siva-chow.github.io/steelwatch/**

### 4. Add your Apify token (so Indeed + Google Jobs turn on)
This is the only secret, and you enter it yourself — it is never shared with anyone.

**Get the token from Apify:**
1. Sign in at https://console.apify.com
2. Go to **Settings → API & Integrations** (or **Integrations**)
3. Copy your **Personal API token** (a long string starting with `apify_api_...`)

**Put it into GitHub:**
1. In your repo: **Settings → Secrets and variables → Actions**
2. Click **New repository secret**
3. Name: `APIFY_TOKEN`  (exactly this, capital letters)
4. Secret: paste your token
5. Click **Add secret**

### 5. Allow the daily job to save its results (important, often missed)
The daily run writes the refreshed jobs back into the repo, so it needs write permission.
1. In your repo: **Settings → Actions → General**
2. Scroll to **Workflow permissions**
3. Select **Read and write permissions** → **Save**
*(Without this, the run works but can't save the new jobs, and the dashboard won't update.)*

### 6. Run it once
1. Go to the **Actions** tab. If you see a banner asking to enable workflows, click **I understand my workflows, go ahead and enable them**.
2. Click **Steelwatch update** (left) → **Run workflow** (right) → **Run workflow**.
3. Wait ~1–2 minutes. It collects roles, scores them, and updates the dashboard.
4. Open your dashboard URL. From now on it also runs automatically every morning at 06:00 UTC.

---

## Everyday use
- Open your dashboard URL. The default **To review** view shows only fresh roles you haven't touched.
- On any role, mark **Applied / In process / Rejected / Not interested**. Applied and closed roles
  drop out of the To-review list so you always see new opportunities first.
- The **pipeline bar** (To review · Applied · In process · Rejected) is your at-a-glance tracker —
  click any of them to see just those roles. **Export CSV** downloads your full application log.
- Filter by country, role type, "New (7 days)," or strong matches only. The header shows which
  feeds reported in on the last run (green = ok, amber ⚠ = needs a look).

**Note on your saved statuses:** application statuses are stored in the browser you use, and survive
the daily data refresh (roles are matched by a stable ID). They don't sync across devices — if you
want laptop/phone sync later, that's a small add-on. Export CSV anytime for a backup.

## Tuning (optional, no coding)
Everything adjustable lives in **config.json**:
- Add or change **search queries** under `sources`
- Turn **Google Jobs** off to save credits: set its `enabled` to `false`
- Company connectors marked `"enabled": false` are mapped but not yet wired — they get switched
  on over time. Until then, Indeed + Google Jobs already cover those companies.

## What's live now vs. coming
- **Live:** Indeed + Google Jobs (cover every target company), the thyssenkrupp Workday feed, and
  the scored dashboard with daily auto-refresh.
- **Coming:** direct career-page connectors for the other ATS platforms (SuccessFactors, Oracle,
  Solique, voestalpine, Recruitee…), added a few at a time so each is verified against the real feed.
