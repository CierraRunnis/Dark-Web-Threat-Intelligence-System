# HTTP Basic Auth

The project can use HTTP Basic Auth as an outer website gate while retaining
the existing application login, accounts, roles, and module permissions.

Add these values to `darkweb_collector/.env` and restart the stack:

```dotenv
DARKWEB_BASIC_AUTH_ENABLED=1
DARKWEB_BASIC_AUTH_USERNAME=site-gate
DARKWEB_BASIC_AUTH_PASSWORD=replace-with-a-long-random-password
DARKWEB_BASIC_AUTH_REALM=Threat Intelligence
DARKWEB_BASIC_AUTH_TTL_SECONDS=43200
```

The first browser request receives the standard HTTP Basic challenge. After
valid credentials are supplied, the gate issues a signed `HttpOnly`,
`SameSite=Strict` cookie. This allows the application to continue using its
existing `Authorization: Bearer ...` header without the two schemes competing
for the same HTTP header. Both layers must succeed for protected API requests.

The password has no built-in default. When Basic Auth is enabled without a
password, both the frontend and API refuse to start.

HTTP Basic credentials are only Base64-encoded, not encrypted. Use this feature
over localhost or behind HTTPS. Do not expose the current plain-HTTP port to an
untrusted LAN or the public Internet.
