# Making MarketPilot live with Cloudflare (free)

MarketPilot keeps running on **your computer**; Cloudflare Tunnel gives it a public HTTPS address without
opening ports on your router. Your PC must stay on (and the windows open) for the site to be reachable.

Remote access always requires a password: in public mode every page and API call needs a login, and a
normal (local) instance refuses any request that arrives through Cloudflare.

## Option A – free, no account, no domain (quick tunnel)

1. Install cloudflared (one time), then open a **new** PowerShell window:
   ```powershell
   winget install --id Cloudflare.cloudflared
   ```
   macOS: `brew install cloudflared` · Linux: download from
   https://github.com/cloudflare/cloudflared/releases
2. Set a strong password in `backend\.env` (12+ characters, not reused elsewhere):
   ```
   APP_PASSWORD=pick-a-long-unique-passphrase
   ```
3. Start everything:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\start-public.ps1
   ```
   (macOS/Linux: `scripts/start-public.sh`)
4. In the output, find the line with **`https://<random-words>.trycloudflare.com`**. Open it on any device and
   sign in with your password.

Limits of quick tunnels: the address **changes every time you restart**, Cloudflare offers them for testing
with no uptime guarantee, and there is a cap on simultaneous requests (fine for one person).

## Option B – permanent address (needs a domain on Cloudflare; the domain is the only cost, ~$10/year)

1. Add your domain to a free Cloudflare account.
2. Create a named tunnel:
   ```powershell
   cloudflared tunnel login
   cloudflared tunnel create marketpilot
   cloudflared tunnel route dns marketpilot marketpilot.yourdomain.com
   ```
3. Create `%USERPROFILE%\.cloudflared\config.yml`:
   ```yaml
   tunnel: marketpilot
   credentials-file: C:\Users\<you>\.cloudflared\<tunnel-id>.json
   ingress:
     - hostname: marketpilot.yourdomain.com
       service: http://localhost:3000
     - service: http_status:404
   ```
4. Start MarketPilot with `scripts\start-public.ps1`, but stop its quick tunnel (Ctrl+C in that window) and run
   `cloudflared tunnel run marketpilot` instead — or install it as a Windows service:
   `cloudflared service install`.
5. Recommended extra layer: in Cloudflare Zero Trust → Access → Applications, protect
   `marketpilot.yourdomain.com` with an email one-time-PIN policy for your address (free for up to 50 users).
   Then visitors must pass Cloudflare's login *and* MarketPilot's password.

## How it works
* The frontend is built in **same-origin** mode (`NEXT_PUBLIC_API_URL=same-origin`): the browser calls `/api/*`
  on the public address and Next.js forwards those calls (including the live WebSocket) to the backend on
  `127.0.0.1:8000`. Only port 3000 is tunnelled; the backend is never exposed directly.
* `PUBLIC_MODE=true` makes the backend require a session cookie (HttpOnly, SameSite=Strict, Secure) for everything
  except `/api/health` and the login endpoints. Failed logins are limited to 5 per IP per 15 minutes. Changing
  `APP_PASSWORD` signs everyone out. The backend refuses to start in public mode without a 12+ character password.
* `scripts/start.ps1` / `start.sh` rebuild the frontend back to local mode automatically if needed.

## Security notes
* Anyone with the password controls your paper trading (start/stop experiments, emergency STOP) and can use your
  AI key if one is configured. Use a unique passphrase and stop the tunnel when you do not need remote access.
* No real-money trading exists in MarketPilot, and API keys are never sent to the browser.
* Signing out: the icon next to STOP in the top bar.
