# Ken Research - Email Campaign System
## Setup Guide for Team Members

---

### What this is
A local tool to send bulk email campaigns from Ken Research's satellite accounts (Alina, Archita, Sneha, Tanushree) via Microsoft's email servers. Tracks who opens your emails.

---

### Step 1 — Install Python (one-time)

1. Go to **https://python.org/downloads**
2. Download the latest version and run the installer
3. **Important:** on the installer screen, check the box that says **"Add Python to PATH"** before clicking Install

---

### Step 2 — Get the project folder

Get the project folder from Vansh (he will share it directly).  
It contains everything — the app, the credentials (`.env`), and this guide.

---

### Step 3 — Start the app

1. Open the project folder
2. Double-click **`START.bat`**
3. A black terminal window will appear — let it run (first time takes ~30 seconds to install dependencies)
4. Your browser will open automatically at `http://localhost:5000`

That's it. The app is running.

---

### Step 4 — Send a campaign

1. In the browser, click **"Send Email"** in the sidebar
2. Fill in:
   - **Campaign ID** — a short name for this campaign (e.g. `ibm_may_2026`)
   - **Sender Account** — pick which account to send from (Alina, Archita, Sneha, or Tanushree)
   - **Recipients** — paste email addresses, one per line
   - **Subject** — your email subject
   - **Body** — your email body (plain text)
3. Click **"Send Campaign"**
4. Emails go out automatically with a 4-5 minute gap between each (to avoid spam filters)

---

### Step 5 — Monitor progress

- Go to **Dashboard** (home page) to see campaigns and open rates
- The dashboard refreshes every 20 seconds automatically
- If a campaign is "pending", click **"Resume"** to continue sending

---

### Stopping the app

Close the black terminal window (`START.bat`). Done.

---

### Tips

- Do not close the terminal while a campaign is actively sending
- If you restart the app mid-campaign, it will automatically resume from where it left off
- Each person runs their own local copy — campaigns do not sync between team members

---

### Something not working?

Contact **Vansh** directly.

