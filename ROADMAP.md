# ROADMAP — Technical Architecture

This document describes *how* LinBot is built: the components, how they fit together, the data flow of a single request, and the order in which we construct everything. Read it alongside `README.md`, which carries the narrative and the session log.

**Teaching note:** A roadmap is not a promise; it's a current best plan. As we learn things during the build, we update this file. When you build your own projects, expect the roadmap to change — that's a sign you're learning, not failing.

---

## 1\. System overview

LinBot is a stateless HTTP backend. A client (course website, chatbot, CLI) sends a student's question; the service asks a language model for an answer and returns it. The *which* model — a hosted API today, our own fine-tuned model tomorrow — is deliberately hidden behind one seam so it can change without the rest of the system noticing.

                 ┌──────────────────────────────────────────────┐

   student's     │                LinBot backend            │

   question      │                                              │

  ───────────►   │   ┌────────┐    ┌────────┐    ┌───────────┐   │

   (HTTP POST)   │   │ server │──► │ model  │──► │  provider │   │

                 │   │ layer  │    │ seam   │    │ (DeepSeek │   │

  ◄───────────   │   └────────┘    └────────┘    │  / HF /…) │   │

   answer (JSON) │        ▲            ▲          └───────────┘   │

                 │        │            │                          │

                 │     config     validation/                    │

                 │    (env vars)   guardrails                     │

                 └──────────────────────────────────────────────┘

Three source components, each with one job:

- **`server`** — owns HTTP: routing, parsing the request, validating input, shaping the JSON response, and returning errors. It knows nothing about *how* answers are generated.  
- **`model`** — the single seam that talks to whichever inference provider is configured. Everything provider-specific lives here and nowhere else.  
- **`config`** — reads settings (API keys, endpoint URLs, model name, limits) from the environment at startup. Nothing else reads env vars directly.

**Why isolate the model seam:** This is the most important design decision in the project, and it becomes *more* important as the project's ambitions grow (see §9). Because *all* provider-specific code lives in one module behind a small interface (`generate_answer(question) -> answer`), we can move from a hosted API to a self-hosted fine-tuned model — or run both at once and split traffic between them — by editing one place. The `server` never changes. This is the "dependency inversion" idea in miniature, and it's what turns "swap the whole model" from a rewrite into a config change.

---

## 2\. The API endpoint

A single route in the first pass:

POST /ask

Content-Type: application/json

Request body:

  { "question": "How does a hash map achieve O(1) lookup?" }

Success (200):

  { "answer": "A hash map ..." }

Errors:

  400  { "error": "question is required and must be a non-empty string" }

  429  { "error": "rate limit exceeded, try again shortly" }

  502  { "error": "the model service is unavailable" }

**Why POST and not GET:** The question is user-supplied content, potentially long, and shouldn't sit in a URL (which gets logged, cached, and shared). A POST body is the correct home for it. This also keeps student questions out of server access logs.

---

## 3\. Request lifecycle (data flow of one call)

1. **Receive** — `server` accepts the POST, parses JSON.  
2. **Validate** — reject missing/empty/oversized questions with a `400`. Fail fast and cheaply *before* spending a model call.  
3. **Rate-limit** — check a simple per-client counter; reject with `429` if over the limit. Protects your budget and the service from abuse.  
4. **Build the prompt** — `model` wraps the question with a fixed **system prompt** that defines the assistant's role (a helpful TA), tone, and boundaries (e.g. "encourage understanding, don't just hand over homework answers").  
5. **Call Claude** — `model` sends the messages to the configured route and awaits the response.  
6. **Handle failure** — network errors, timeouts, or an overloaded model become a clean `502`, never a stack trace leaked to the client.  
7. **Return** — extract the text from the model's response and return it as JSON.

**Why validate and rate-limit *before* the model call:** Every model call costs tokens (money) and latency. Cheap checks up front — is this even a valid request? is this client flooding us? — protect both. Order your pipeline cheapest-check-first.

---

## 4\. The model seam in detail

The interface is intentionally tiny:

generate\_answer(question: str) \-\> str

Everything below this line is an implementation detail the rest of the app never sees. Each provider is one implementation of the same `generate_answer` signature, so `server` calls them identically:

- **DeepSeek direct (pass one):** reads the DeepSeek API key from config and calls DeepSeek's hosted endpoint with the chosen model, system prompt, and question. This is the cheapest, simplest starting point. DeepSeek's API accepts both OpenAI- and Anthropic-style request formats, so the client code is straightforward either way.  
- **Self-hosted fine-tuned model on Hugging Face (later phases):** points at a Hugging Face Inference Endpoint URL serving our own fine-tuned checkpoint, with a config-supplied auth token.  
- **Fallback provider:** an already-working provider (initially DeepSeek direct) that requests fall through to when the primary is erroring, timing out, or cold-starting. See §9.

**Why a system prompt lives here and is fixed in code:** The system prompt shapes *every* answer — it's the difference between a raw model and "a TA for this course." Keeping it versioned in the repo (not user-supplied) means behavior is reviewable, testable, and can't be overridden by whatever a student types. Never let the request body silently become the system prompt.

### Model selection

The provider, model name, and any endpoint URL are config values, not hardcoded constants, so you can move between providers — or between versions of your own model — without a code change. Choose based on the difficulty of the questions, your budget, and (later) how your fine-tuned iterations are performing against the base model. Verify current model names and per-token prices in the official documentation before committing to one — model lineups and prices change.

**A note on the earlier Claude routes:** earlier sessions explored serving answers via the Claude API or the Claude Agent SDK on a subscription. Those remain valid implementations of this same seam, but the project's end goal (a self-hosted fine-tuned model) makes an open-weight base model the more natural starting point, so the active plan below is built around DeepSeek → Hugging Face. Nothing about the seam forecloses going back to a Claude provider if wanted.

---

## 5\. Configuration and secrets

`config` reads, at startup:

| Variable | Purpose | Phase |
| :---- | :---- | :---- |
| `PROVIDER` | Which provider the seam uses (`fake`, `deepseek`, `hf`) | all |
| `DEEPSEEK_API_KEY` | Auth for the DeepSeek hosted API | 1+ |
| `HF_ENDPOINT_URL` | URL of the self-hosted fine-tuned model endpoint | 2+ |
| `HF_TOKEN` | Auth for the Hugging Face Inference Endpoint | 2+ |
| `HF_MODEL_NAME` | Name/version of the fine-tuned model on the endpoint | 2+ |
| `MODEL_NAME` | Which model/version to call on the primary provider | all |
| `CANARY_PROVIDER` | Candidate provider receiving canary traffic | 2+ |
| `CANARY_PERCENT` | Share of traffic (0–100) sent to the candidate model | 2+ |
| `FALLBACK_PROVIDER` | Known-good provider used when the chosen one fails | 2+ |
| `DATABASE_URL` | Postgres connection string for the request log (Railway-style `postgres://` URLs are normalized automatically) | all |
| `RATE_LIMIT` | Max requests per client per window | all |
| `RATE_LIMIT_WINDOW_SECONDS` | Length of the rate-limit window | all |
| `PORT` | Port the HTTP server binds to | all |

`.env.example` lists these names with placeholder values. The real `.env` is git-ignored.

**Why fail loudly if a required var is missing:** A server that boots with no API key and only discovers it on the first request produces a confusing runtime error under load. Validate config at startup and refuse to boot if something required is absent. Loud, early failure beats silent, late failure.

---

## 6\. Build sequence

We build in the order that keeps failures easy to localize — plumbing first, intelligence second.

1. **Scaffold \+ hello-world endpoint.** `POST /ask` returns a hardcoded string. No model yet. *Proves the HTTP layer works in isolation.* ✅ (Session 3)  
2. **Config loading.** Read env vars, fail loudly if required ones are missing. ✅ (Session 3)  
3. **Model seam with a fake.** Implement `generate_answer` as a stub that echoes the question. *Proves the server↔model wiring without spending tokens.* ✅ (Session 3)  
4. **Request logging.** Persist each question, the model that answered, and the answer in Postgres — the raw material for both fine-tuning data and evaluation (see §9–§10). ✅ (Session 3 — pulled forward from step 7 because the schema is the project's most durable asset and every later step benefits from the data)  
5. **Real DeepSeek implementation.** Wire the stub to the DeepSeek API. First real answers. ✅ (Session 3 — code complete; needs a real `DEEPSEEK_API_KEY` to go live)  
6. **Guardrails.** Input validation, then rate limiting, then clean error handling for model failures. ✅ (Session 3)  
7. **Tests.** Unit-test validation and the model seam (with the fake); integration tests for the endpoint; CI on every push. ✅ (Session 3)

Steps 1–7 are pass one. The phased model-rollout work (§9) and evaluation harness (§10) begin once pass one is serving real traffic and accumulating logged questions. Scheduling and mailbox remain deferred throughout.

**Why build the fake model before the real one:** You want to prove your architecture end-to-end without money or network flakiness in the loop. If the request reaches a stub that echoes the question and comes back as JSON, every layer *except* the model is verified. Then swapping in the real call isolates any new failure to exactly one place.

---

## 7\. Deliberately deferred (first pass excludes)

- **Scheduling / calendar** — no time-based features in pass one.  
- **Mailbox / email** — no sending or receiving mail.  
- **Persistence** — no database; the service is stateless. Conversations aren't remembered between requests.  
- **Auth for end users** — the first pass assumes a trusted caller.

Each is a natural "next chapter." Recording them here means when future-you returns, the omissions read as decisions with a paper trail, not gaps.

---

## 9\. Model rollout strategy (the research direction)

The project's end goal is no longer "call a hosted model." It is to **train our own model for this task and release it as a series of measured iterations**, each one deployed on Hugging Face Inference Endpoints and rolled out gradually against live traffic. This section describes the architecture that makes that safe. It is the heart of what turns this from a side project into a research direction: the product (answering students) and the research (does our fine-tuned model actually beat the baseline?) share one system.

### The three phases

**Phase 1 — Baseline in production.** Serve every request with base DeepSeek V4 Flash. Log every question and answer. The point of this phase is not just to ship something useful; it is to **collect the real distribution of student questions**, which becomes both the fine-tuning dataset and the evaluation set. You cannot fine-tune well for a task you haven't yet observed.

**Phase 2 — First self-hosted iteration behind a canary.** Deploy fine-tuned model `v1` on a Hugging Face Inference Endpoint. Route a small, configurable share of traffic to it (`CANARY_PERCENT`) while the rest continues to the DeepSeek baseline. Compare the two on real questions. This is a *canary release*: you expose the new model to a trickle of traffic first, watch, and widen the split only as confidence grows.

**Phase 3 — Iterate.** Each new fine-tuned version is a candidate: canary it, evaluate it against the incumbent, then **promote** (make it the primary) or **roll back** (revert `CANARY_PERCENT` to zero). Over time the "incumbent" becomes your own model and the baseline becomes the fallback. The fine-tuning workflow itself — curating logged questions into training data, training, versioning checkpoints on the Hub — runs as a parallel track feeding candidates into this loop.

### Components the rollout requires

The `model` seam widens from "one provider" to "a router over several providers":

- **Provider abstraction** — DeepSeek-direct and each HF endpoint implement the same `generate_answer` interface. (You already have this from pass one.)  
- **Routing / traffic split** — a mechanism to send `CANARY_PERCENT` of requests to the candidate model and the remainder to the incumbent. Start as simple as a weighted random choice per request.  
- **Fallback path** — if the primary provider errors, times out, or is cold-starting, the request quietly falls back to a known-good provider (initially DeepSeek direct) rather than failing the student.  
- **Per-request model attribution in logs** — record *which* model answered each request, so quality comparisons can be attributed correctly. Without this, an A/B comparison is meaningless.

**Why the fallback path is not optional here:** Hugging Face Inference Endpoints with scale-to-zero **cold-start** when traffic is sparse — the first request after an idle period can be slow. For a waiting student that's a bad experience. Early iterations especially, wire the baseline fallback in. Whether to keep the endpoint warm (costs more) or tolerate cold starts (cheaper, slower) is a cost/latency knob you tune as usage grows — but the fallback should exist from the first self-hosted deployment.

**Why gradual instead of a hard swap:** A staged rollout means a regression in your new model is discovered at 5% of traffic, not 100%. "Slowly releasing iterations" isn't caution for its own sake — it's what lets you ship improvements you can actually verify and undo the ones you can't.

---

## 10\. Evaluation harness

Once two models are answering live traffic, **the harness that tells them apart is as important as the models themselves.** A gradual rollout is only meaningful if you can answer "is the candidate better than the incumbent?" — otherwise you're shipping fine-tunes on vibes.

Minimum viable evaluation for this project:

- **A held-out set of real student questions** with known-good reference answers, drawn from the Phase 1 logs. Every candidate model is scored against this set *before* it ever sees live traffic.  
- **Scoring on the dimensions you care about** — correctness, helpfulness, appropriate tone, not-just-handing-over-homework-answers. Some of this can be automated (exact-match or reference-based checks); some may need human review or an LLM-as-judge approach. Decide per dimension.  
- **Live comparison** — because logs record which model answered (§9), you can compare candidate vs. incumbent on the real traffic each handled during a canary.

**Why build the eval set early:** The held-out set is what makes each "iteration" in the rollout a measured step rather than a guess. Students routinely skip this and can't tell whether their fine-tune helped. Building even a lightweight version during Phase 1 — while you're already logging questions — is what makes Phases 2 and 3 rigorous.

---

## 11\. Updated deferrals and scope

Still explicitly **out of scope**, unchanged from the first pass: scheduling/calendar, mailbox/email, and end-user auth.

**Now in scope** as a result of the expanded research direction: request logging with model attribution, a provider router with traffic-splitting and fallback, self-hosted fine-tuned model deployment on HF Inference Endpoints, and an evaluation harness. These are sequenced across Phases 1–3 above rather than built all at once.

The **fine-tuning workflow** (dataset curation, training, checkpoint versioning) is its own track and will get its own detailed roadmap section when Phase 2 begins; for now it is named but not specified, so the intent is on record without a premature commitment to tooling.

---

## 12\. Architectural principles to carry forward

- **One seam per external dependency.** Anything outside your code (a model, a database, an email provider) hides behind one interface. Swapping providers should touch one file — and here, that one seam is what makes the entire staged-rollout strategy possible.  
- **Roll out changes gradually and reversibly.** New models reach users through a canary and can be rolled back with a config change, never a redeploy.  
- **Measure before promoting.** No model version becomes the primary without being scored against the held-out set.  
- **Every request is also data.** Log questions, answers, and which model produced them — this is both your fine-tuning corpus and your evaluation ground truth.  
- **Always have a fallback.** A cold or failing primary should degrade to a known-good provider, not to an error.  
- **Cheapest checks first.** Validate and rate-limit before expensive work.  
- **Secrets in the environment, never in git.**  
- **Fail loudly and early** on misconfiguration; **fail cleanly and quietly** (no leaked internals) on runtime errors.  
- **Version your prompts** like code, because they *are* part of your program's behavior.

