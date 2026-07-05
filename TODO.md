- [x] Update app/dashboard/app.js to gracefully handle unauthenticated state before protected API calls
- [x] Improve fetch error parsing for cleaner API error messages
- [x] Handle 401 token-expiry by clearing token and rendering auth-required guidance
- [x] Preserve normal auto-refresh behavior for authenticated sessions
- [x] Validate behavior by reloading /dashboard with and without token
- [ ] Add inline dashboard login form wired to POST /api/usersPlan (frontend-only UX fix + “linked to backend properly”):

**Information Gathered**
- `app/dashboard/app.js` already renders a consistent auth-required UI when `access_token` is missing or invalid and handles 401 by clearing the token.
- Current dashboard HTML (`app/dashboard/index.html`) has **no login form/UI**, so users can’t easily create/set the token using the existing backend route `POST /api/users/login`.

**Plan (file-level)**
1) `app/dashboard/index.html`
   - Add an inline login form (email + password) and a logout button.
   - Add a dedicated `<div id="authPanel">` to show guidance and login errors.
   - Keep existing panels, but ensure the auth panel is visible when unauthenticated.

2) `app/dashboard/app.js`
   - Add functions:
     - `setAuthUIState(state, payload)` to show/hide auth UI.
     - `login()` to call `POST /api/users/login` using `application/x-www-form-urlencoded` (matches `OAuth2PasswordRequestForm`).
     - `logout()` to clear token.
   - Wire auth UI into current auth-required behavior.
   - When login succeeds: store `access_token`, then trigger a refresh immediately.

**Dependent Files to edit**
- `app/dashboard/index.html`
- `app/dashboard/app.js`

**Follow-up steps**
- Restart/refresh the running server and manually test:
  - No token → auth panel visible.
  - Login with correct credentials → panels load and refresh.
  - Logout → returns to auth panel.
  - Invalid login → show readable error from backend.

