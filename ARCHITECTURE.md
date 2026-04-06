# Crat8Cloud — Billing & Multi-Tenant SaaS Architecture

> **Model: Option 1 — Operator-hosted.** Users pay Crat8Cloud. All data lives in our AWS account. We manage storage, auth, billing, and infrastructure. Users get a desktop app that connects to our backend.

---

## Table of Contents

1. [Multi-Tenant S3 Storage Design](#1-multi-tenant-s3-storage-design)
2. [Pricing Tiers](#2-pricing-tiers)
3. [Stripe Billing Integration](#3-stripe-billing-integration)
4. [Cognito Auth + Stripe Customer Creation Flow](#4-cognito-auth--stripe-customer-creation-flow)
5. [API Layer](#5-api-layer)
6. [Desktop App Communication Flow](#6-desktop-app-communication-flow)
7. [Data Isolation and Security](#7-data-isolation-and-security)
8. [Infrastructure Cost Estimates](#8-infrastructure-cost-estimates)
9. [Implementation Roadmap](#9-implementation-roadmap)

---

## 1. Multi-Tenant S3 Storage Design

### Bucket Structure

We use a **single bucket, prefix-isolated** multi-tenant model. One bucket per environment (prod/staging), with all tenants sharing it. This simplifies IAM, reduces overhead, and scales to millions of users without hitting AWS account limits.

```
crat8cloud-prod/
├── users/
│   └── {user_id}/
│       ├── tracks/
│       │   └── {hash[:2]}/          ← 256 prefix shards for S3 performance
│       │       └── {sha256_hash}/
│       │           └── {filename}   ← original filename preserved
│       ├── serato/
│       │   ├── database_v2          ← Serato database backup
│       │   └── crates/
│       │       └── {crate_name}.crate
│       └── metadata/
│           └── library.json         ← denormalized library snapshot for fast restore
└── shared/
    └── crews/
        └── {crew_id}/
            └── {user_id}/
                └── {hash[:2]}/{hash}/{filename}   ← shared tracks
```

### Key Design Decisions

**Hash-addressed storage (`{hash[:2]}/{hash}/`):**
- Enables deduplication: two users who own the same track only need one copy. We store the file once, reference it from both user records in DynamoDB.
- The 2-character prefix distributes keys across S3 partitions, avoiding hotspots at scale.
- Content-addressed means we can detect file corruption on restore (re-hash and compare).

**Single bucket, IAM-enforced isolation:**
- Bucket policy + IAM role conditions enforce that the desktop app can only read/write its own `users/{user_id}/` prefix. The Cognito identity pool issues temporary credentials scoped to the user's prefix.
- A Lambda sidecar enforces quota before any upload proceeds.

**Serato metadata backup (`serato/` prefix):**
- The entire `_Serato_` database and all `.crate` files are backed up alongside the audio, so a full restore recovers the DJ's cues, loops, and playlists — not just the MP3s.

**Versioning:**
- S3 versioning enabled. Users can roll back to a prior library state (e.g., recovering accidentally deleted cue points). Older versions expire after 90 days via a lifecycle rule to control cost.

---

## 2. Pricing Tiers

DJ library sizes vary enormously — a hobbyist might have 2,000 tracks (~20 GB) while a touring DJ can have 20,000+ tracks (~400 GB). Pricing is designed around actual DJ usage patterns.

| Tier | Name | Price | Storage | Key Features |
|------|------|-------|---------|--------------|
| **Free** | Spin | $0/mo | 5 GB | Single device, manual backup only, no crew sharing |
| **Pro** | Mix | $9/mo | 100 GB | Auto-backup, 1 crew, cross-device sync, priority support |
| **Pro+** | Drop | $19/mo | 500 GB | Auto-backup, 5 crews, faster uploads, restore to any device |
| **Unlimited** | Residency | $39/mo | 2 TB | Everything in Drop, unlimited crews, Serato metadata versioning, dedicated support |

**Overage pricing (Pro/Pro+ only):**
- $0.05/GB per month beyond the tier limit, billed monthly.
- Residency has no overage — it's truly unlimited at 2 TB.

**Annual discount:** 2 months free (pay 10, get 12).

### Rationale

- **Free tier** (5 GB) covers ~500 MP3s — enough to try the product with a real library subset. Drives word-of-mouth in DJ communities.
- **Mix** ($9) is the primary conversion target. 100 GB = ~10,000 MP3s at typical bitrates, which covers most working club DJs.
- **Drop** ($19) targets full-time and touring DJs with large libraries across multiple laptops.
- **Residency** ($39) is for professionals and DJ agencies managing multiple accounts or very large libraries. Positions as cheaper than Dropbox Pro for the same use case.

---

## 3. Stripe Billing Integration

### Architecture

```
Desktop App
    │
    ▼
API Gateway (/billing/*)
    │
    ▼
Lambda: BillingService
    ├── Stripe API
    └── DynamoDB: users table (stripe_customer_id, subscription_id, tier, quota_bytes)
```

### Stripe Resources Per User

| Resource | When Created | Purpose |
|----------|--------------|---------|
| `Customer` | On Crat8Cloud account creation | Links Cognito user to Stripe billing identity |
| `Subscription` | When user selects a paid plan | Tracks recurring billing, trial periods |
| `PaymentMethod` | At checkout | Stored on Stripe, never touches our servers |
| `UsageRecord` | If overage billing enabled | Reports GB-hours above tier limit |

### Subscription Flow

```
1. User signs up (free tier)
   → Cognito creates user
   → PostConfirmation Lambda triggers
   → Stripe Customer created (email from Cognito)
   → DynamoDB record: { tier: "free", quota_bytes: 5GB, stripe_customer_id: "cus_..." }

2. User upgrades to Mix ($9/mo)
   → Desktop app opens Stripe Checkout (hosted page) via API
   → User enters card on Stripe's servers (PCI-compliant, never touches us)
   → Stripe sends webhook: checkout.session.completed
   → Webhook Lambda updates DynamoDB: { tier: "mix", quota_bytes: 100GB, subscription_id: "sub_..." }
   → Desktop app polls /billing/status and reflects new quota

3. Monthly renewal
   → Stripe sends: invoice.payment_succeeded
   → Webhook Lambda: no-op (subscription already active)

4. Payment failure
   → Stripe sends: invoice.payment_failed (retries 3x over 7 days)
   → After final failure: customer.subscription.deleted
   → Webhook Lambda: { tier: "free", quota_bytes: 5GB }
   → User's existing files are NOT deleted — grace period of 30 days before storage is reclaimed

5. Cancellation
   → User cancels via desktop app → API → Stripe
   → Stripe sends: customer.subscription.deleted at period end
   → Webhook Lambda downgrades to free tier at billing cycle end
```

### DynamoDB User Record Schema

```json
{
  "user_id": "cognito-sub-uuid",
  "email": "dj@example.com",
  "stripe_customer_id": "cus_abc123",
  "subscription_id": "sub_xyz789",
  "tier": "mix",
  "quota_bytes": 107374182400,
  "storage_used_bytes": 43000000000,
  "created_at": "2025-01-15T10:00:00Z",
  "subscription_status": "active",
  "billing_period_end": "2025-02-15T10:00:00Z"
}
```

---

## 4. Cognito Auth + Stripe Customer Creation Flow

### Signup Flow (End-to-End)

```
User fills signup form in desktop app
         │
         ▼
Cognito: SignUp API
  (email + password, email verification sent)
         │
         ▼
User confirms email (verification code)
         │
         ▼
Cognito: PostConfirmation trigger → Lambda
  ┌──────────────────────────────────────────┐
  │  PostConfirmationLambda:                 │
  │  1. Create Stripe Customer               │
  │     stripe.customers.create({            │
  │       email: event.request.userAttributes│
  │         .email,                          │
  │       metadata: { cognito_sub: user_id } │
  │     })                                   │
  │  2. Write DynamoDB record                │
  │     { user_id, tier: "free",             │
  │       quota: 5GB,                        │
  │       stripe_customer_id }               │
  │  3. Create S3 "folder" marker            │
  │     (optional: PUT users/{id}/.keep)     │
  └──────────────────────────────────────────┘
         │
         ▼
User lands in app, free tier active
```

### Token Flow for API Calls

```
Desktop App
  │  1. Sign in via Cognito (USER_PASSWORD_AUTH)
  │  2. Receive: AccessToken, IdToken, RefreshToken
  │
  ▼
API Gateway
  │  Authorization: Bearer {IdToken}
  │
  ▼
Lambda Authorizer (or built-in Cognito authorizer)
  │  Validates token against User Pool
  │  Injects user_id from sub claim
  │
  ▼
Business Logic Lambda
  │  Uses user_id to query DynamoDB for tier/quota
  │  Performs action (upload, quota check, etc.)
```

Tokens expire after 1 hour. The desktop app uses the RefreshToken (24-hour validity) to silently renew. Stored in macOS Keychain via the `keyring` library (already implemented in `config.py`).

---

## 5. API Layer

### Stack Choice: API Gateway + Lambda (serverless)

Serverless is the right fit here — usage is bursty (DJs open the app, trigger a backup, close it), not steady-state. No idle compute cost.

### API Endpoints

```
POST   /auth/signup              → Proxy to Cognito (or direct SDK from app)
POST   /auth/confirm             → Proxy to Cognito
POST   /auth/login               → Proxy to Cognito

GET    /billing/status           → Returns { tier, quota_bytes, used_bytes, subscription_status }
POST   /billing/checkout         → Creates Stripe Checkout session, returns URL
POST   /billing/cancel           → Cancels Stripe subscription at period end
POST   /billing/portal           → Returns Stripe Customer Portal URL (manage payment methods)
POST   /billing/webhooks         → Stripe webhook receiver (HMAC-verified)

GET    /library/quota            → Returns { used_bytes, quota_bytes, can_upload: bool }
POST   /library/upload-url       → Returns presigned S3 URL for a single track upload
  body: { filename, file_hash, file_size, content_type }
  logic: check quota, check if hash already exists (dedup), return presigned PUT URL
POST   /library/upload-complete  → Called after successful presigned upload
  body: { s3_key, file_hash, metadata: { title, artist, bpm, ... } }
  logic: update DynamoDB track record, increment storage_used_bytes
GET    /library/tracks           → Paginated list of user's tracks with metadata
DELETE /library/tracks/{hash}    → Delete a track, decrement storage_used_bytes

GET    /crews                    → List user's crews
POST   /crews                    → Create a crew
POST   /crews/{crew_id}/invite   → Generate invite code
POST   /crews/{crew_id}/join     → Join via invite code
GET    /crews/{crew_id}/library  → Browse shared tracks in a crew
```

### Upload Flow Detail (Presigned URL Pattern)

The desktop app never streams audio through Lambda — that would be slow and expensive. Instead:

```
Desktop App                    API Lambda                    S3
     │                              │                         │
     │  POST /library/upload-url    │                         │
     │  { filename, hash, size }    │                         │
     │ ─────────────────────────► │                         │
     │                              │  Check quota in DynamoDB│
     │                              │  Check if hash exists   │
     │                              │  (dedup: return existing│
     │                              │   key if already stored)│
     │                              │  Generate presigned URL │
     │                              │  (15 min expiry)        │
     │ ◄───────────────────────── │                         │
     │  { upload_url, s3_key }      │                         │
     │                              │                         │
     │  PUT {upload_url}            │                         │
     │  [audio file bytes]          │                         │
     │ ──────────────────────────────────────────────────── ► │
     │                              │              200 OK     │
     │ ◄──────────────────────────────────────────────────── │
     │                              │                         │
     │  POST /library/upload-complete                         │
     │  { s3_key, hash, metadata }  │                         │
     │ ─────────────────────────► │                         │
     │                              │  Update DynamoDB        │
     │                              │  Increment used_bytes   │
     │ ◄───────────────────────── │                         │
     │  200 OK                      │                         │
```

### Quota Enforcement

Quota is checked at **presigned URL generation time** (not at upload time — S3 doesn't call back to Lambda during a PUT). The Lambda checks:

```python
if user.storage_used_bytes + file_size > user.quota_bytes:
    raise QuotaExceededError(
        used=user.storage_used_bytes,
        quota=user.quota_bytes,
        requested=file_size
    )
```

A separate nightly Lambda reconciles `storage_used_bytes` in DynamoDB against actual S3 usage (via `list_objects_v2`) to catch any drift.

---

## 6. Desktop App Communication Flow

### Startup

```
1. App launches
2. Load config from ~/.crat8cloud/config.json
3. Load credentials from macOS Keychain
4. If credentials exist: attempt token refresh (Cognito)
   - Success: mark as authenticated, fetch billing status
   - Failure: prompt re-login
5. Fetch GET /billing/status → update UI with tier/quota display
6. Start file watcher on music paths
7. Check pending uploads, begin upload worker (if authenticated)
```

### Upload Worker

```
1. Scan library → find PENDING/MODIFIED tracks
2. For each track (sorted by size, smallest first):
   a. POST /library/upload-url
      → if quota exceeded: pause worker, notify user
      → if duplicate (hash exists): mark SYNCED, skip upload
      → if ok: receive presigned URL
   b. PUT presigned URL (direct to S3, no Lambda in path)
      → stream with progress callback → update menu bar %
   c. POST /library/upload-complete
      → mark track SYNCED in local SQLite DB
3. Repeat until queue empty
4. Update last_sync timestamp
```

### Auth Token Refresh

The desktop app proactively refreshes the Cognito token 5 minutes before expiry (tokens last 1 hour). The refresh token lasts 30 days by default (configurable in Cognito). If refresh fails (e.g., user logs in on a new device and old session is invalidated), the app catches the 401 from API Gateway and prompts re-login.

---

## 7. Data Isolation and Security

### Tenant Isolation at S3

**Cognito Identity Pool** issues temporary AWS credentials scoped to a single user's prefix:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::crat8cloud-prod/users/${cognito-identity.amazonaws.com:sub}/*"
    },
    {
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::crat8cloud-prod",
      "Condition": {
        "StringLike": {
          "s3:prefix": "users/${cognito-identity.amazonaws.com:sub}/*"
        }
      }
    }
  ]
}
```

The `${cognito-identity.amazonaws.com:sub}` variable is resolved by AWS at credential issuance time — a user can never forge another user's prefix even if they inspect their own temporary credentials.

**Presigned URLs** (used for direct upload) are scoped to a specific S3 key and expire in 15 minutes. They cannot be reused for a different key.

### API-Level Isolation

Every Lambda function extracts `user_id` from the **Cognito JWT claims** (not from the request body). The app never trusts a user-supplied user_id:

```python
# Correct — user_id from verified JWT
user_id = event["requestContext"]["authorizer"]["claims"]["sub"]

# Wrong — never do this
user_id = json.loads(event["body"])["user_id"]
```

### DynamoDB Isolation

Each DynamoDB operation uses `user_id` as the partition key. No cross-tenant queries are possible in the current schema. Access patterns are user-scoped by design.

### Encryption

| Layer | Encryption |
|-------|-----------|
| S3 at rest | AES-256 (SSE-S3, enabled at bucket level) |
| S3 in transit | TLS 1.2+ enforced via bucket policy (`aws:SecureTransport`) |
| DynamoDB at rest | AWS-managed KMS key (enabled by default) |
| API Gateway | HTTPS only, TLS 1.2+ |
| Credentials on device | macOS Keychain (AES-256 hardware-backed on Macs with Secure Enclave) |
| Config on device | `~/.crat8cloud/credentials.json` with 0o600 permissions (fallback if no Keychain) |

### Crew Sharing Security

When a DJ shares tracks with a crew:
- A **time-limited presigned URL** is generated for each shared track (24-hour default).
- The crew member's client downloads via the presigned URL — they never get S3 credentials for the owner's prefix.
- Shared tracks are **copied** into `shared/crews/{crew_id}/{owner_id}/` so revocation (removing a member) stops future access without affecting the original.

---

## 8. Infrastructure Cost Estimates

All prices use AWS us-east-1 pricing as of 2025. S3 is the dominant cost driver.

### Assumptions

| Metric | Value |
|--------|-------|
| Avg library size per active user | 50 GB |
| Avg uploads per user/month | 200 tracks (~2 GB) |
| Avg downloads per user/month | 1 full restore per quarter = ~12 GB/mo amortized |
| API calls per user/month | ~500 (uploads + status checks) |
| DynamoDB reads/writes per user/month | ~2,000 |

### Cost Breakdown

#### 100 Users (early stage)

| Service | Usage | Monthly Cost |
|---------|-------|-------------|
| S3 Storage | 100 users × 50 GB = 5 TB | $115 |
| S3 PUT requests | 100 × 200 uploads = 20,000 | $0.10 |
| S3 GET requests | 100 × 500 gets = 50,000 | $0.02 |
| S3 data transfer out | 100 × 12 GB = 1.2 TB | $108 |
| Lambda (API) | 100 × 500 calls × 200ms × 256MB | ~$0.50 |
| API Gateway | 50,000 requests | $0.18 |
| DynamoDB | 200,000 R/W, 1 GB storage | ~$1.00 |
| Cognito | 100 MAU (free tier: 50,000) | $0 |
| **Total** | | **~$225/mo** |
| Revenue (mix avg) | 80 paid × $9 = | **$720/mo** |
| **Gross margin** | | **~69%** |

#### 1,000 Users

| Service | Usage | Monthly Cost |
|---------|-------|-------------|
| S3 Storage | 1,000 × 50 GB = 50 TB | $1,150 |
| S3 PUT requests | 200,000 | $1.00 |
| S3 GET requests | 500,000 | $0.20 |
| S3 data transfer out | 12 TB | $1,080 |
| Lambda | ~$5 | $5 |
| API Gateway | 500,000 requests | $1.75 |
| DynamoDB | 2M R/W, 10 GB storage | ~$5 |
| Cognito | 1,000 MAU | $0 |
| **Total** | | **~$2,243/mo** |
| Revenue (mix avg) | 800 paid × $9 | **$7,200/mo** |
| **Gross margin** | | **~69%** |

#### 10,000 Users

| Service | Usage | Monthly Cost |
|---------|-------|-------------|
| S3 Storage | 10,000 × 50 GB = 500 TB | $11,500 |
| S3 PUT requests | 2M | $10 |
| S3 GET requests | 5M | $2 |
| S3 data transfer out | 120 TB | $10,800 |
| Lambda | ~$50 | $50 |
| API Gateway | 5M requests | $17.50 |
| DynamoDB | 20M R/W, 100 GB | ~$50 |
| Cognito | 10,000 MAU | $0 (free tier) |
| CloudFront (CDN for downloads) | 120 TB out (replaces S3 egress at lower rate) | ~$8,400 |
| **Total (with CloudFront)** | | **~$20,830/mo** |
| Revenue (mix avg) | 8,000 paid × $9 | **$72,000/mo** |
| **Gross margin** | | **~71%** |

### Key Cost Optimization Notes

1. **S3 data transfer is the biggest variable cost.** At scale, put CloudFront in front of S3 for restores/downloads — CloudFront egress is $0.07/GB vs S3's $0.09/GB, and it reduces origin load.

2. **Deduplication pays off.** If even 20% of tracks are shared across users (common DJ records), S3 storage cost drops proportionally while revenue stays flat. At 10,000 users with 20% dedup, storage drops from 500 TB to ~400 TB — saving ~$2,300/mo.

3. **S3 Intelligent-Tiering** for tracks older than 90 days not accessed: automatically moves to Infrequent Access at ~40% cost reduction. A DJ's 2018 tracks that are "backed up but rarely restored" would benefit.

4. **Lambda is not a meaningful cost** at any of these scales. Don't over-engineer the compute layer.

5. **Cognito is free up to 50,000 MAU.** No cost pressure until serious scale.

6. **Reserved capacity for DynamoDB** becomes worth it at 10,000+ users — switch from on-demand to provisioned + auto-scaling for ~30% savings.

---

## 9. Implementation Roadmap

### ✅ Phase 1 (Core Backup) — Complete

Upload pipeline, file watcher, Serato parser, SQLite sync engine, Cognito auth, S3 client, CLI commands, and auto-backup scheduler are all wired and tested.

---

### Phase 1.5 (Zero-Config Onboarding)

**Goal: Install → Sign up → You're backed up. No manual configuration.**

The current app requires the user to set music paths, configure AWS credentials, and run `crat8cloud config`. That's a barrier. This phase eliminates it entirely.

1. **Auto-detect Serato installation** — on first launch, scan the standard locations (`~/Music/_Serato_`, `/Volumes/*/Music/_Serato_`) and find the Serato folder automatically. If multiple are found, prompt the user to pick one.
2. **Auto-discover music folders** — parse the Serato `database V2` file to extract all root music paths referenced by the existing library. Pre-populate `music_paths` in config without the user having to type anything.
3. **Guided first-run flow** — a simple 3-step window: (1) confirm detected Serato path + music folders, (2) sign up / log in, (3) show first backup starting. No AWS configuration exposed to the user — credentials come from the backend API at login.
4. **Remove direct AWS config requirement** — once the Phase 3 API layer exists, the desktop app gets temporary credentials from the API after login. Users never see bucket names, regions, or access keys.
5. **Background initial scan** — after first-run, kick off `scan_and_index()` silently in the background. Menu bar shows progress. User can keep working.

---

### Phase 2 (Restore, Sync & Gig Recovery)

**Goal: What goes up must come down — reliably, completely, and fast.**

1. **`crat8cloud restore` CLI command** — download tracks from S3 back to a local path, reconstructing the original folder structure. Supports filtering by crate or date range.
2. **Cross-device sync** — compare local SQLite state against the S3/DynamoDB manifest. Pull down tracks present in cloud but missing locally, push up anything new locally.
3. **🎯 Gig Recovery Mode** — one-click full library restore to a new machine:
   - DJ signs into Crat8Cloud on a fresh Mac
   - Hits "Recover My Library" in the app
   - App downloads the last-known Serato `database V2` snapshot and all `.crate` files first (fast, small) so Serato can launch immediately with the correct crate structure
   - Tracks download in priority order: crates marked as "active sets" or most recently played first, then the full library in the background
   - Serato-specific metadata (cue points, loops, beatgrids, BPM, keys, colors) is embedded back into each audio file's tags on restore, not just stored in the DB
   - Progress visible in menu bar: "Recovering: 1,240 / 15,298 tracks"
   - DJ can start playing from recovered tracks while the rest download
   - Target: a DJ should be able to play a gig within 30 minutes of signing in on a new machine
4. **Restore verification** — after download, re-hash each file and compare against stored SHA-256. Flag any corrupted files for re-download.

---

### Phase 3 (Backend API) — required for SaaS model

1. Provision AWS infrastructure (CDK or Terraform):
   - S3 bucket (versioning, encryption, lifecycle rules)
   - Cognito User Pool + Identity Pool
   - DynamoDB tables: `users`, `tracks`, `crews`
   - API Gateway + Lambda functions
2. Implement PostConfirmation Lambda (Stripe customer creation)
3. Implement billing endpoints + Stripe webhook handler
4. Implement presigned upload URL endpoint with quota enforcement
5. Update desktop app to use API instead of direct AWS SDK calls (enables Zero-Config Onboarding)

### Phase 4 (Crew Sharing)

1. Crew CRUD endpoints + invite code system
2. Shared library browser in the window UI
3. Presigned URL generation for crew track access

### Phase 5 (Web Dashboard)

1. Next.js or similar — account management, billing portal, library overview
2. Embedded Stripe Customer Portal for payment method management
