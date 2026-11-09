# Deploying ResolveAI (public demo link)

Target: **Render free web service** using the included `Dockerfile` and `render.yaml`.
Result: one public URL, for example `https://resolveai-xxxx.onrender.com`. The customer chat is at `/` and the admin dashboard at `/admin`.

## Status
The `Dockerfile` was written but **not built in the development environment** (Docker Hub was unreachable there). The frontend build and the Python dependency install it runs were each tested separately. If the Render build fails, paste the build log.

## Before you start
* Free Render services **sleep after ~15 minutes idle**. The first visit then takes ~1 minute to wake. Open the link a minute before you present.
* Free Render storage is **temporary**: cases in the dashboard are cleared when the service restarts or redeploys. The **Resolution Logs in Google Sheets are permanent**.
* Free Render **blocks Gmail's SMTP ports**, so the hosted app sends Gmail through a Google Apps Script over HTTPS (step 2). Your laptop setup (App Password) keeps working as before.

## 1. Put the project on GitHub
1. Create a **private** repository on github.com (for example `resolveai`).
2. Upload the `ResolveAI` folder contents (the folder that has `Dockerfile`, `backend`, `frontend`, `docs`).
   **Do NOT upload** `backend/.env` or `backend/credentials/`. The `.gitignore` already excludes them if you use Git or GitHub Desktop.

## 2. Gmail over HTTPS (Apps Script), 5 minutes
1. Signed in as the Gmail account that should send, open https://script.google.com → **New project**.
2. Replace the code with `docs/gmail_apps_script.gs`. Change `SECRET` to a long random string. Save.
3. **Deploy → New deployment** → gear icon → **Web app** → *Execute as:* **Me** → *Who has access:* **Anyone** → **Deploy** → authorise (Advanced → Go to project → Allow).
4. Copy the **Web app URL** (ends in `/exec`).

## 3. Create the Render service
1. https://render.com → sign up with GitHub → **New → Blueprint** → choose your repo → Render reads `render.yaml`.
2. Fill in the secret values when asked:

| Key | Value |
|---|---|
| `GOOGLE_API_KEY` | your Gemini key |
| `GOOGLE_SHEETS_SPREADSHEET_ID` | `1LH_nxEDzeoK2ges_MSkYcigfoDHxTQ8PX2TuoeLIeOA` |
| `GMAIL_WEBHOOK_URL` | the Apps Script `/exec` URL |
| `GMAIL_WEBHOOK_SECRET` | the same SECRET you put in the script |
| `EMAIL_DEMO_RECIPIENT` | your Gmail address (all demo emails go here) |
| `ADMIN_PASSWORD` | a strong password, not the one you use locally |

3. After the service is created: **Environment → Secret Files → Add**. Filename `service_account.json`, contents = paste the whole JSON key file. Save (it is mounted at `/etc/secrets/service_account.json`).
4. **Manual Deploy → Deploy latest commit**. The first build takes ~5 minutes.

## 4. Check it
1. Open the URL. The banner should read **Planner: Gemini · Data: Google Sheets · Email: Gmail … via Apps Script**.
2. Run *"Please cancel my order ORD1006"*, approve in `/admin`, confirm the email arrives and a row appears in Resolution Logs.

## Security notes for a public link
* Anyone with the link can use the chat and spend your Gemini free quota. Share it only with your instructor, and turn the service off after grading (Settings → Suspend).
* The admin dashboard is password-protected. Use a strong `ADMIN_PASSWORD`.
* All emails go to `EMAIL_DEMO_RECIPIENT`, so the public cannot use the app to email arbitrary people.
