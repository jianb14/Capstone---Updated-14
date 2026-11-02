# Redis cache on Railway

The project uses Django's built-in `RedisCache` with the `redis` Python client.
`REDIS_URL` selects Redis; an unset/blank URL keeps local development on
`LocMemCache`. Railway's start command runs `check_cache --require-redis` before
starting the web server, so a missing or unreachable Redis cannot silently fall
back to a cache that is different in each worker.

## Railway setup (sunod-sunod)

1. Open the Railway project and the **same environment** as the deployed Django
   service (usually Production).
2. Click **+ New**, select **Database**, then **Redis**. Keep the name `Redis` if
   you want to use the exact reference below. Deploy/apply the staged addition
   if Railway asks, then wait until the Redis service is running. Keep its
   default private connection.
3. Open the **Django application service**, then **Variables**. Add:

   ```env
   REDIS_URL=${{Redis.REDIS_URL}}
   ```

   The variable belongs on the Django service. If the Redis service has a
   different name, use **Add Reference** to select that service's `REDIS_URL`
   instead. Do not reference the Django service itself and do not use
   `REDIS_PUBLIC_URL`. The reference includes the credentials automatically.
4. Save/apply the variables. Do steps 1-3 **before deploying the new code**:
   `railway.toml` now requires a working Redis connection at startup.
5. Commit and push this change to the branch connected to the Railway Django
   service. Include these files:

   - `.env.example`
   - `Project/cache_config.py`
   - `Project/settings.py`
   - `requirements.txt`
   - `railway.toml`
   - `app/management/commands/check_cache.py`
   - `app/test_redis_cache.py`
   - `docs/redis.md`

   Wait for the deployment from that commit. If automatic deployments are
   disabled, deploy the latest commit from the connected branch. Redeploying an
   old image alone will not include the new dependency or configuration.
6. Open the Django deployment's **Deploy Logs**. Before the migration/static
   output and Gunicorn startup, look for:

   ```text
   Cache OK: RedisCache (write/read, atomic add, delete).
   ```

   This line comes from a real write/read check in the running Railway network.
   A merely running Redis service is not proof that Django is using it.
7. Open the website and check a saved design preview and a venue/place search.
   Both already use Django's cache and will now share it across workers.

No separate cache migration/table, Celery service, or change to the database URL
is needed for this setup. Railway installs the Python dependency from
`requirements.txt` during the build. The Redis service uses Railway resources;
check its resource usage in the dashboard.

## What is cached

| Data | Existing expiration |
| --- | --- |
| Design card WebP previews | 24 hours; new image filenames produce new keys |
| Successful place searches/reverse geocoding | 24 hours |
| Empty geocoding results | 60 seconds |
| Shop coordinates resolved from address | 24 hours; changing the address changes the key |
| Unresolved shop coordinates | 60 seconds |
| AI style quiz cooldown | 10 seconds, shared atomic `add()` |

The default lifetime is 300 seconds when code does not specify a timeout.
`CACHE_KEY_PREFIX` defaults to `balloorina`; use a different prefix if deliberately
sharing one Redis instance between multiple apps/environments.

Bookings, payment records, login sessions, OTPs, general abuse-protection
counters, and the AI job queue remain in their existing database storage.
Availability and pricing are still checked by the existing application code.
In-process AI knowledge/document caches and local geometry parsing remain as
they are. Installing Redis does not automatically cache every query or page.

The default cache uses finite connection/read timeouts. Redis errors are not
globally ignored because the same cache also enforces the quiz cooldown. Keep
Redis running while the application uses it.

## Manual connection check

Inside the **deployed Django container**, run:

```bash
python manage.py check_cache --require-redis
```

If Railway CLI is already configured, `railway ssh` opens a shell in the deployed
service; select/link the Django service and the correct environment first. A
local `railway run`/`railway shell` process still runs on your laptop and cannot
reach `*.railway.internal` through Railway's private network.

The command tests binary/structured data, atomic add, and deletion. It uses one
random temporary key with a 30-second expiry and deletes only that key. It never
clears the cache or prints the connection URL/password.

## Local development and tests

Leave `REDIS_URL` unset or empty in your local `.env` to keep using the application
without installing a Redis server. To use your own local Redis, set:

```env
REDIS_URL=redis://127.0.0.1:6379/0
```

After installing `requirements.txt`, these checks work with either backend:

```bash
python manage.py check
python manage.py check_cache
python manage.py test app.test_redis_cache --settings=Project.test_settings --noinput
```

The optional TCP integration tests use a disposable Redis protocol emulator,
Django's real Redis backend, and the real Python Redis client. To include them:

```bash
python -m pip install "fakeredis>=2.28,<3"
python manage.py test app.test_redis_cache --settings=Project.test_settings --noinput
```

`fakeredis` is a test dependency only and is not installed on Railway. These tests
verify shared connections, concurrent atomic add, expiration, binary previews,
geocoding reuse, and prefix isolation. The startup check validates the actual
Railway Redis connection after you configure it.

## If deployment fails

- **Redis is required, but ... LocMemCache**: the Django service has no resolved
  `REDIS_URL`. Add the reference variable on that service, apply it, and deploy
  again. Check the Redis service name in the reference.
- **REDIS_URL must be a valid ... URL**: check for an unresolved `${{...}}`
  reference, quotation marks pasted into the value, or the wrong variable.
- **Cache check failed (RedisCache)**: verify Redis is running, credentials are
  current, and both services are in the same project/environment. Run diagnostic
  commands in the deployed container rather than on the laptop.
- **No module named redis / unknown command check_cache**: the deployed build
  does not contain this change. Deploy the latest connected-branch commit.

## Official references

- [Railway Redis setup](https://docs.railway.com/databases/redis)
- [Railway private networking](https://docs.railway.com/networking/private-networking)
- [Private networking during build versus runtime](https://docs.railway.com/networking/private-networking/how-it-works)
- [Railway SSH](https://docs.railway.com/cli/ssh)
- [Django Redis cache](https://docs.djangoproject.com/en/5.0/topics/cache/#redis)
