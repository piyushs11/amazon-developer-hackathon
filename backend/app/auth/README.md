# auth

**Owner:** Dev 3

Platform user tokens (C8), upstream OAuth A1–A5, token vault, refresh.

| File | What |
|---|---|
| `identity.py` | `user_from_token()`: JWT from demo-login, or `DEMO_USER_TOKEN` → `demo-user`; `get_current_user` dependency (bare 401) |
| `router.py` | `POST /auth/demo-login {username}` → `{user_id, user_token}` |
| `oauth.py` | `build_auth_url(user_id, service_uuid)`, `handle_callback(code, state)`, `callback_redirect()`, `refresh()` |
| `state.py` | HMAC-signed `state` (10 min) |
| `vault.py` | `InMemoryTokenStore`, `LocalTokenStore` (Postgres, Fernet-encrypted) |
| `factory.py` | `get_identity/get_token_store/get_mapping/get_token_provider`, `configure()` at startup |

## For Dev 4
```python
from backend.app.auth.identity import get_current_user          # Depends() on /api routes
from backend.app.auth.oauth import build_auth_url, handle_callback, callback_redirect

@router.get("/oauth/start")
def oauth_start(service_uuid: str, user_id: str = Depends(get_current_user)):
    return {"auth_url": build_auth_url(user_id, service_uuid)}

@router.get("/oauth/callback")
async def oauth_callback(code: str, state: str):
    return RedirectResponse(callback_redirect(await handle_callback(code, state)))
```
`/me/services`: `get_mapping().list_for_user(user_id)`.
