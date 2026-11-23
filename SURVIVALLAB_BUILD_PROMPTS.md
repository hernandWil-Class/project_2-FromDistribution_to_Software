# SurvivalLab: complete build prompts

This is the single build guide for the complete SurvivalLab application. Work on
one milestone at a time. Each milestone is a self-contained prompt, but it
depends on the shared contract and the successful criteria of earlier
milestones.

## How to use this guide

1. Open the SurvivalLab workspace and read the shared contract.
2. Select the next incomplete milestone. Do not start a later milestone while a
   required earlier milestone is incomplete or failing.
3. Implement its steps in the workspace; inspect the existing code and preserve
   unrelated work.
4. Run the stated success checks. Report commands and results that actually
   occurred; distinguish blocked or untested checks.
5. If implementation reveals a conflict, missing assumption, or incorrect
   instruction, fix this guide in the same change. Keep the success criteria
   measurable and consistent with the implementation.
6. Update the progress record at the end of this file, then stop at the
   milestone boundary unless asked to continue.

Each milestone uses four headings: **Objective**, **Context**, **Steps**, and
**Success criteria**. These four are preferable to combining everything into
three: the objective states the result, context gives its rationale and
constraints, steps prescribe the work, and independently testable success
criteria prevent a plausible-looking implementation from being mistaken for a
working one.

## Shared project contract

### Goal and limits

Build a teaching application for exponential-survival maximum-likelihood
estimation and sound software practices. Use synthetic data only. This is an
educational model, not a clinical predictor, an individual diagnosis, or
clinical advice.

### Environment and workflow

- Detect the actual host OS, architecture, shell, and WSL status before giving
  or running commands. Do not assume macOS, native Linux, WSL, or Windows
  PowerShell. Use POSIX-style commands in macOS/Linux/WSL shells; use the WSL
  shell for WSL projects rather than Windows PowerShell. Native Windows
  PowerShell is not a substitute unless the guide is explicitly updated for it.
- Keep instructions relative to the workspace root. Detect the Python
  interpreter with `uv`; use `uv python install 3.11` and `uv python pin 3.11`
  only when Python 3.11 is missing or the project pin is not already valid.
- Treat Docker Desktop or Docker Engine availability as a host-specific fact:
  start only the service supported on that host, and never claim Docker or
  Compose is usable until `docker info` and a disposable smoke container pass.
- Add host-specific setup facts to this section under
  "Environment verification record"; keep prior-host evidence, and label each
  record with its actual OS, shell, architecture, and date.
- On macOS, prefer the host package manager that is already installed (for
  example Homebrew) for missing system tools. On Debian/Ubuntu or WSL, use the
  distribution package manager. On Fedora/RHEL or Arch derivatives, use the
  host distribution's package manager instead of assuming `apt`. Record all
  installation commands actually used.
- Docker Desktop on macOS or Windows/WSL is usable as the Docker host; native
  Docker Engine is typically used in Linux and WSL distributions. Docker
  socket access must never be mounted into containers.
- Use Python 3.11. Keep the application runnable locally. Docker Compose may
  provide PostgreSQL and orchestration services; do not require a cloud
  account.
- Label commands with the shell they require. Be explicit about manual steps.
  Never claim to have installed, started, or verified something that was not
  actually checked.
- Work locally. Do not push, publish, deploy externally, upload data, commit
  without permission, or delete Docker volumes. `down` must preserve data.
- This guide is the only Markdown file in the workspace. Do not create a
  separate README, progress file, architecture document, runbook, or milestone
  prompt. Put project instructions, verified setup facts, progress, limitations,
  and learning notes in this file. Notebooks may contain Markdown cells.
- Do not add fake command targets, success-shaped fallbacks, silent filtering,
  or broad exception handling. Errors must remain visible and actionable.
- Prefer focused tests for new behavior. Do not claim that a test, scan,
  notebook, service, or integration check passed unless it was run.

### Statistical contract

- Time zero is diagnosis; time is measured in months. The event is death from
  any cause. Assumptions: independent patients, independent right censoring,
  and one constant common hazard.
- Use the rate parameter `lambda` (λ), not the scale. NumPy's exponential
  `scale` and lifelines `ExponentialFitter.lambda_` are `1/lambda`.
- Inputs are equal-length one-dimensional duration and event arrays. Durations
  must be finite and strictly positive. Events must be exactly 0 or 1 and must
  be validated before any cast.
- `n = number of subjects`, `D = sum(event)`, and `Y = sum(duration)`.
  Estimate `lambda_hat = D / Y` only when `D > 0`. If `D = 0`, return an
  explicit not-fitted/boundary status and do not publish an estimate.
- `S(t) = exp(-lambda_hat * t)` is the probability of remaining event-free
  beyond `t`. `P(event by t) = -expm1(-lambda_hat * t)`.
  `mean = 1/lambda_hat`; `median = ln(2)/lambda_hat`.
- Reject negative or non-finite horizons. JSON must not contain NaN or
  Infinity.
- Provide asymptotic log-Wald and likelihood-ratio intervals. Never call a
  censored-data chi-square interval “exact.” State assumptions and units.
- Fixed fixture: IDs `P001`–`P008`, durations
  `[6, 10, 12, 15, 18, 20, 24, 30]`, events `[1, 0, 1, 0, 1, 0, 1, 0]`.
  Expected `D=4`, `Y=135`, `lambda_hat=4/135`, and
  `S(24)=0.4910982295`.
- Additional demo cases: add censored `P009` at 36 months to get `4/171`;
  resending the identical observation changes nothing; revising `P002` from 10
  to 16 months (as a new valid version) gives `4/141`.

### Architecture and data contract

- Python 3.11 package in `src/survivallab`; notebooks import the package and do
  not hold a second permanent implementation.
- PostgreSQL 16 schemas: `raw`, `meta`, `model`, and `analytics`. Alembic owns
  `raw`, `meta`, and `model`; dbt owns analytics models.
- Separate dependency environments/locks for the application, dbt, and
  Airflow. Pin compatible versions only after checking their official,
  versioned documentation; record verified versions here.
- FastAPI accepts observations and serves published aggregate model results.
  Streamlit calls the API only; it never connects to PostgreSQL.
- Airflow 3 schedules the same refresh operations as the manual command.
  GitHub Actions checks code and tests only; it does not deploy.
- No Kafka, Kubernetes, Redis, cloud services, Docker-socket mount, or
  unverified compatibility assumptions.
- Observation fields: UUID `observation_id`, `patient_id`, integer
  `version >= 1`, finite positive `duration_months`, binary `event_observed`,
  UTC `observed_at`, `ingested_at`, and canonical `payload_hash`. Uniqueness:
  `(patient_id, version)`.
- Same patient/version and same content is idempotent. Same patient/version
  with different content is a conflict. Normal revisions cannot shorten
  follow-up or undo an observed event. Corrections require a reason and a
  reference to the prior observation.
- A cohort uses the latest accepted version for each patient. Create a
  snapshot manifest in one `REPEATABLE READ` transaction, storing its member
  observation IDs and a hash of ordered content. Never use a max-ID watermark.
  New records after snapshot creation belong to a later snapshot.
- Refresh flow: snapshot (reused on retry) → source tests → dbt build → fit →
  validate → atomic publish. Skip unchanged cohorts. Allow one run at a time
  using an application/database lock. A failure keeps the last valid model.
  Persist provenance (snapshot, code/config hashes, method, units, versions,
  timestamps); never put datasets in Airflow XCom.

### Security and presentation contract

- Bind host ports to `127.0.0.1`; use separate local credentials, least-
  privilege database roles, parameterized SQL, non-root containers, and no
  secrets in source or logs. Protect writes with `X-API-Key` and constant-time
  comparison.
- Do not return or display raw patient observations. Aggregate model data only.
- Dashboard data entry includes patient ID, version, follow-up months, and
  event Yes/No. Saving an observation and refreshing the model are separate
  actions. Selecting a month calculates from the current published model; it
  does not silently trigger a fit.
- Make stale published output, a failed candidate, unavailable services, and a
  successful refresh visibly distinct. Never label stale output as current.
- Passing tests and scans do not establish clinical validity or production
  readiness.

## M00 — Verify the local environment

### Objective

Record which local tools are actually available and make the development
workspace ready without assuming WSL or changing unrelated machine settings.

### Context

The original plan assumed Windows 11 + WSL2, but a workspace may instead be on
macOS or native Linux. This milestone verifies the current host and only
requests manual installation if a later-required tool is missing. It must not
change global shell settings or assume a package manager.

### Steps

1. In a POSIX shell, run the following read-only detection commands:

   ```sh
   printf 'host=%s\narch=%s\nshell=%s\n' \
     "$(uname -s)" "$(uname -m)" "${SHELL:-unknown}"
   uname -a
   if [ -n "${WSL_DISTRO_NAME:-}" ] || grep -qi microsoft /proc/version 2>/dev/null; then
     echo 'environment=WSL'
   elif [ "$(uname -s)" = Darwin ]; then
     echo 'environment=macOS'
   elif [ "$(uname -s)" = Linux ]; then
     echo 'environment=Linux'
   else
     echo 'environment=other'
   fi
   python3 --version 2>/dev/null || true
   uv python find 3.11 2>/dev/null || true
   git --version
   curl --version | head -n 1
   make --version | head -n 1
   uv --version
   docker --version
   docker compose version
   docker info --format '{{.OperatingSystem}} | {{.Architecture}}'
   ```

   On a macOS shell, `/proc/version` may not exist; the detection command must
   remain valid. Do not run WSL-only detection as a mandatory macOS step.
2. Inspect the project for a `.python-version` or existing uv configuration.
   Confirm Python 3.11 is selected for project commands. Use
   `uv python install 3.11 && uv python pin 3.11` only if needed. Keep separate
   host and project interpreters explicit; do not substitute Python 3.12+
   silently for Python 3.11.
3. Verify Docker Compose can run a harmless disposable container. A portable
   first check is:

   ```sh
   docker run --rm hello-world
   docker compose version
   ```

   If Compose supports it, also run a disposable hello-world service and
   remove it automatically:

   ```sh
   docker compose -f /dev/null config
   ```

   Do not delete volumes or alter global shell configuration. Docker Desktop
   must be running on macOS/Windows hosts; Docker Engine must be running on
   native Linux. On WSL, verify that Docker Desktop WSL integration or the
   native Docker daemon is actually reachable.
4. Record actual versions, passed checks, manual steps, and untested checks in
   the environment section of this file. Distinguish "Verified", "Unavailable",
   "Untested", and "Previously verified on another host".

### Success criteria

- Host and shell are identified from command output.
- Python 3.11, Git, curl, Make, uv, Docker, and Compose are either verified or
  explicitly marked unavailable/untested.
- No unrelated settings, credentials, or persistent data are changed.

### Student exercise

Explain the difference between the host OS, shell, Python interpreter, and
Docker Compose.

## M01 — Create the package and development workflow

### Objective

Create a small installable Python package with a working CLI, reproducible
dependencies, and focused quality checks.

### Context

The statistics and validation code must be importable by notebooks, the API,
and jobs. A `src` layout and lockfile make those imports and installations
repeatable.

### Steps

1. Create a Python 3.11 `src/survivallab` package and `pyproject.toml` with
   minimal justified core dependencies and optional/dependency groups for dev,
   notebook, database/API, dbt, and Airflow work as they are introduced.
2. Generate and keep a lockfile in the workspace; do not make a Git commit
   unless asked. Avoid self-referential extras (the inherited scaffold used
   `survivallab[db]` inside the `survivallab` API extra, which is cyclic) and
   keep application, dbt, and Airflow dependency resolution isolated.
3. Add a CLI entry point with `survivallab --help`, a small pure function, and
   readable application logging.
4. Review the existing `pyproject.toml` before relying on it; it was present
   as a partial scaffold before M01 started. Validate dependency extras and
   lockfile behavior with a clean environment rather than assuming it works.
5. Add Ruff, pytest, mypy, and pre-commit configuration. Add portable VS Code
   settings without absolute paths.
6. Add `.gitignore`, `.gitattributes` (LF for scripts), `.env.example` with
   empty placeholders, and a Makefile with truthful `help`, `doctor`, `setup`,
   `test`, and `quality` targets. Add later targets only when implemented.
7. Keep user-facing setup, project notes, and agent instructions in this single
   build guide; do not add `README.md`, `AGENTS.md`, or another Markdown file.

### Success criteria

- Clean installation from the lockfile succeeds under Python 3.11.
- `survivallab --help` works from an installed environment.
- The package imports outside the source directory.
- A real unit test, formatting, lint, and type checks pass; report any
  baseline limitations explicitly.

### Student exercise

Add a small validated function and test, then stop at a debugger breakpoint.

## M02 — Add synthetic study data

### Objective

Create deterministic fixture and generated datasets with strict validation and
clear censoring semantics.

### Context

Every model and integration example must use synthetic observations. Keep
latent simulation truth separate from the fit-facing observed data.

### Steps

1. Implement the fixed eight-patient fixture in the shared contract.
2. Add a seeded generator with event time `T ~ Exponential(rate=0.03/month)`,
   censor time `C ~ Uniform(12, 60)`, observed duration `min(T, C)`, and
   `event=1(T<=C)`. Validate generator parameters and preserve full precision.
3. Give patients stable IDs and versions starting at 1. Accept a fixed
   timestamp or explicit input for reproducible fixtures.
4. Write observed CSV, simulation-truth CSV, and generator metadata
   separately. Never include latent event times in fit-facing output.
5. Add strict Pydantic v2 models: forbid extra fields; reject non-finite or
   non-positive durations; reject non-binary events before casting (including
   0.5); enforce UTC timestamps and month units.
6. Implement `survivallab generate` and `survivallab validate` with predictable
   schemas and row-level validation errors.
7. Add a notebook that loads observations and plots follow-up by event status;
   do not fit a model in this milestone.
8. Add the field definitions and censoring explanation below to this guide.

### Success criteria

- Same seed produces identical observed data and metadata; different seeds
  produce different cohorts.
- Round-trip, value-range, malformed-row, extra-field, non-finite, and
  non-binary-event tests pass.
- The fixed fixture gives `D=4`, `Y=135`; observed output contains no latent
  times.
- The notebook runs from a clean kernel and its output is synthetic-only.

### Student exercise

Change the censoring distribution and explain why the observed event fraction
can change while the simulated true survival distribution stays the same.

### M02 data dictionary

| Observed-data field | Meaning |
|---|---|
| `patient_id` | Synthetic subject ID, stable within the cohort (for example `P001`). |
| `version` | Positive integer for the immutable observation version; the initial fixture/generator version is `1`. |
| `duration_months` | Observed follow-up in months: `min(event_time, censor_time)`, always finite and positive. |
| `event_observed` | Integer `1` when the event occurred by the censor time; integer `0` when the record is right-censored. |
| `observed_at` | Time the synthetic observation was recorded, as an ISO-8601 UTC timestamp. |

`observed.csv` contains only these observed fields. `simulation_truth.csv`
contains the latent event and censor times for teaching/evaluation only; never
use those columns to fit the model. `metadata.json` records the seed, cohort
size, true simulation rate, censoring distribution, and fixed observation
timestamp. Censored observations contribute their known follow-up duration,
but do not assert that the event happened at that time.

## M03 — Derive the likelihood

### Objective

Teach the exponential-survival likelihood in a reproducible notebook that uses
the package fixture.

### Context

Students need to understand why censored follow-up contributes survival
probability rather than event density before relying on an estimator.

### Steps

1. Derive density, CDF, survival, hazard, complete and censored likelihood,
   log-likelihood, derivatives, and the MLE. Explain why a censored patient
   contributes `S(t)`, not `f(t)`, and state assumptions.
2. On the fixture compare correct `D/Y` against treating every observation as
   an event and against discarding censored observations.
3. Compute mean, median, `S(12)`, `S(24)`, `S(60)`, interval event
   probabilities, and conditional survival. Explain memorylessness, possible
   unsuitability for cancer survival, and extrapolation beyond observed
   follow-up.
4. Plot likelihood versus rate and the survival curve. Verify a numerical
   optimizer in log-rate coordinates against `D/Y`; compare with lifelines
   `ExponentialFitter` using rate = `1/lambda_`.
5. Keep any temporary estimator clearly marked for replacement in M04; do not
   maintain a second permanent implementation.
6. Include short exercises with separate answer cells.

### Success criteria

- The notebook runs from a clean kernel and imports the fixture/library as
  specified.
- Numerical answers match package results within stated tolerances.
- Censoring, assumptions, and limitations are explained without calling the
  model an individual or clinical predictor.

### Student exercise

Derive the same estimator using the scale parameter `theta`.

## M04 — Implement the statistical library

### Objective

Implement and test pure statistical functions for fitting, prediction,
uncertainty, and model diagnostics.

### Context

The notebook is teaching material; the package is the single authoritative
implementation used by the CLI and later services.

### Steps

1. Move notebook logic into `src/survivallab/stats`. Implement fit,
   log-likelihood, survival, event probability using `expm1`, interval event
   probability, conditional survival, mean, median, and rate intervals.
2. Validate array rank, equal lengths, finite positive durations, exact binary
   events before casting, and finite non-negative prediction horizons.
3. Implement asymptotic log-Wald and likelihood-ratio intervals. Use a
   bracketed root solver in log-rate and chi-square with one degree of freedom
   for the LR interval. Clearly state asymptotic status.
4. Return a structured boundary/not-fitted result for `D=0`; never emit
   NaN/Infinity or publish this result.
5. Add a `fit-csv` CLI command returning structured JSON, assumptions, and
   units. Add a separate reproducible coverage/bias simulation script, not a
   unit test.
6. Add Kaplan–Meier diagnostics and a Weibull misspecification exercise to the
   notebook; the estimator remains exponential.

### Success criteria

- Tests cover fixture values, `S(0)=1`, monotonicity, rate/scale equivalence,
  unit invariance, malformed/mismatched arrays, zero events, empty inputs,
  invalid horizons, analytic versus optimizer results, and interval endpoint
  reversal.
- Fixture LR interval is approximately `[0.0091985194, 0.0688318046]`;
  log-Wald interval at `z=1.96` is approximately
  `[0.01112033, 0.07894685]`.
- All valid JSON outputs are finite; zero-event output is explicit and
  not-fitted.

### Student exercise

Show how duplicate patients leave the rate unchanged but falsely shrink its
standard error.

## M05 — Add PostgreSQL, migrations, and ingestion

### Objective

Persist immutable observations and reproducible analysis snapshots in a local
PostgreSQL service.

### Context

The application needs versioned inputs and immutable membership so retries and
historical models can be reproduced. dbt, HTTP, and Airflow are not part of
this milestone.

### Steps

1. Add Docker Compose with a pinned PostgreSQL 16 image, named volume,
   healthcheck, and optional `127.0.0.1` host port. Reserve schemas
   `raw`, `meta`, `model`, `analytics`; provision a distinct migration role
   and least-privilege runtime roles. Airflow's metadata database/role can be
   provisioned when Airflow is introduced, not as a fake unused stub.
2. Add SQLAlchemy 2, PostgreSQL driver, and Alembic. Migrations own
   `raw`, `meta`, and `model`; analytics is reserved for dbt.
3. Create observations (unique `(patient_id, version)`), snapshots,
   snapshot-members, candidate fits, active-model pointer, and pipeline-run
   tables with constraints and indexes justified by queries.
4. Implement ingestion: identical content/hash/version returns existing;
   different content at same version conflicts. Normal revisions cannot shrink
   follow-up or undo an event. Corrections require reason and prior-observation
   reference. Hash patient content, not retry timestamps.
5. Create snapshot membership and content hash in one `REPEATABLE READ`
   transaction. Select latest accepted version per patient at snapshot time;
   store member IDs. Reuse an unchanged snapshot. Do not use a max-ID
   watermark.
6. Add Make targets `up`, `migrate`, `seed-fixture`, `db-shell`, `down`, and
   `init-local-secrets`. `down` must preserve volumes; never generate secrets
   into tracked files.
7. Add disposable-PostgreSQL integration tests.

### Success criteria

- Migrations create the expected schemas/tables and can be applied twice
  safely.
- Tests verify identical duplicates, conflicts, revision/correction rules,
  snapshots, inserts after a snapshot, and restart persistence.
- New post-snapshot observations do not change the old snapshot; `down`
  preserves stored data.
- Tests use disposable local data and leave user volumes intact.

### Student exercise

Query raw history and the current cohort; explain why their row counts differ.

## M06 — Add dbt transformations and data checks

### Objective

Build analytics models from immutable snapshot membership and block invalid
data before fitting.

### Context

Alembic owns raw/meta/model schemas; dbt owns analytics. The snapshot already
selects member observation IDs. dbt must not recalculate “latest patient”
independently for each task.

### Steps

1. Create an isolated locked dbt Core + dbt-postgres environment and
   environment-variable-based profile using the least-privilege analytics
   role.
2. Build staging, snapshot-member join, analysis cohort, and per-snapshot
   sufficient-statistics (`n`, `D`, `Y`) models. Start with views so historical
   snapshots remain queryable and are not deleted.
3. Add tests for source relations, unique `(snapshot_id, patient_id)`,
   relationships, not-null, positive finite time, binary event, `D<=n`, and
   aggregate reconciliation. Do not silently filter bad rows.
4. Run source checks before fitting and use `dbt build` for build+tests.
   Document compiled SQL and how to inspect failing rows in this guide.
5. Add `make dbt-build` and `make dbt-docs`; generate docs/lineage as command
   output, not a separate Markdown artifact.
6. Cross-check `n=8`, `D=4`, `Y=135` with non-integer division and guarded
   denominator. Python remains estimator authority.

### Success criteria

- Two revisions yield one patient per snapshot; old snapshot counts remain
  stable.
- Every required test passes on the fixture.
- A deliberate data-quality failure fails `dbt build` and prevents fitting.
- SQL and Python sufficient statistics agree exactly (within numeric type
  tolerance for `Y`).

### Student exercise

Add a duplicate in a scratch database, observe the test fail, then fix it.

### M06 inspection commands

- `make dbt-build` runs model builds and all source/model tests; a failing test
  returns a non-zero status and the refresh flow must stop before fitting.
- `uv run --locked --group dbt dbt compile --project-dir dbt --profiles-dir dbt`
  writes compiled SQL under
  `dbt/target/compiled/survivallab_analytics/models/`.
- To inspect invalid fit-facing rows after a failed test, query the analytics
  view (never query raw patient identifiers in the dashboard):

  ```sql
  SELECT snapshot_id, duration_months, event_observed
  FROM analytics.analysis_cohort
  WHERE duration_months <= 0
     OR duration_months >= 'Infinity'::double precision
     OR event_observed NOT IN (0, 1);
  ```

## M07 — Add FastAPI and synchronous refresh

### Objective

Provide a secured API for ingestion, published predictions, status, and a
single manual refresh flow.

### Context

Ingestion never fits. Saving a patient update and calculating survival at a
chosen horizon are not the same operation as refreshing the model.

### Steps

1. Build FastAPI with Pydantic request/response models and injected
   repositories. Implement `GET /health/live`, `GET /health/ready`,
   `POST /observations`, `GET /models/latest`, `GET /models/{model_id}`,
   `GET /survival?months=24`, `GET /pipeline/status`, and aggregate
   Kaplan–Meier curve output. Never expose raw observations.
2. Require `X-API-Key` for writes, compare in constant time, never log it, and
   parameterize SQL. Return 201 for new, 200 for identical retry, 409 for
   same-version conflict, 422 for invalid input, and 503 when no valid model
   exists.
3. Implement the synchronous refresh command: snapshot → source tests → dbt
   build → fit → validate → atomic publish. Track task status/errors, lock
   concurrent refreshes, enforce candidate uniqueness by snapshot/code/config/
   method, and persist provenance. Exercise the API with its separate ingest,
   pipeline, and read database roles; do not use the migration role as a
   substitute for runtime permissions.
4. Reuse the same snapshot during retry. Skip unchanged cohorts; code/config
   changes may refit. Keep the previous model on any failed candidate.
5. Add `make refresh` and `make status`; expose the API as a non-root local
   Compose service.

### Success criteria

- API tests cover fixture ingest/prediction, identical retry, conflicts,
  historical model stability, no-model response, invalid horizons, failed
  publish, and finite JSON.
- Adding censored P009 at 36 months changes rate to `4/171`; resend changes
  nothing.
- An unchanged refresh is skipped. A failed dbt candidate leaves the old
  model, rate, and publication timestamp active.
- API response schemas contain aggregates only.

### Student exercise

Compare raw HTTP, Swagger, and a Python client for the same read request.

## M08 — Add Airflow 3 orchestration

### Objective

Schedule the verified refresh operations using Airflow 3 without duplicating
pipeline logic.

### Context

Airflow is optional orchestration around the M07 pipeline, not the owner of
business logic. It is the heaviest local service and must be version-checked.
The official Airflow Docker quick start recommends at least 4 GiB for Docker,
so the standard startup target applies a conservative 4 GiB preflight. This is
not a hard Airflow minimum. In this workspace, the pinned profile ran with
7,678,930,944 bytes of Docker memory; the full stack became healthy and
scheduled refresh tasks succeeded. No lower-memory minimum is inferred.
References: [Airflow 3.4 installation prerequisites](https://airflow.apache.org/docs/apache-airflow/3.4.0/installation/prerequisites.html)
and [Docker Compose quick start](https://airflow.apache.org/docs/apache-airflow/3.4.0/howto/docker-compose/index.html).

### Steps

1. Verify a compatible pinned Airflow 3 image/Python using official
   version-specific documentation. Use a separate Compose profile, Local
   Executor, API server, scheduler, DAG processor, triggerer,
   initializer/auth setup, and dedicated metadata database. Configure the
   same randomly generated JWT signing secret in components that exchange
   Execution API tokens. Do not use Airflow 2 commands or assume unverified
   compatibility.
2. Have the DAG call the secured `POST /pipeline/refresh` API. This reuses the
   already-tested API pipeline and its locked application/database environment,
   avoids duplicating fit logic or installing dbt in Airflow, and makes a
   nonzero/failed API result fail the task. XCom may contain only run status
   and run ID, never data. No Docker socket, per-run `pip install`, or secrets
   in DAG source.
3. Create a DAG that runs every minute with `catchup=False`,
   `max_active_runs=1`, manual trigger, and two bounded retries. It calls the
   same pipeline as `make refresh` through the API.
4. Reuse the snapshot across retries; skip unchanged input; retain database
   lock protection for manual concurrency; publish only after validation.
   Record failures and downstream skips.
5. Add `make orchestration-up`, `make orchestration-down`, and
   `make orchestration-status`; keep Airflow outside default startup and make
   ordinary shutdown preserve metadata volumes.

### Success criteria

- DAG imports in the pinned image and succeeds against the seeded fixture.
- Real image tests cover fixture run, unchanged-input skip, ingest-then-refresh,
  forced dbt failure preserving the prior model, and idempotent retry.
- UI/API prediction remains available when Airflow is stopped.
- Report measured latency as an observation, not an SLA. If Docker is
  unavailable, mark integration checks blocked; do not claim success.
- `make orchestration-up` refuses to start below the project's conservative
  4 GiB preflight threshold; this is a project safety policy, not a hard
  Airflow minimum.

### Student exercise

Stop Airflow while querying predictions; explain which component remains
available and why.

## M09 — Add the Streamlit dashboard

### Objective

Provide a clear local interface for recording observations and exploring
aggregate model predictions without direct database access.

### Context

The interface shown in the infographic is a concept, not evidence that a
dashboard exists. The implementation must use FastAPI only and clearly
separate write, refresh, and prediction actions.

### Steps

1. Build a Streamlit app using an HTTP client with timeouts; never connect to
   PostgreSQL. Add the dashboard to default Compose startup.
2. Add a patient update form for ID, version, follow-up months, and event
   Yes/No. Save through the API. Enforce append-only versions and display
   validation/conflict errors. For an explicit correction, collect the
   previous observation UUID and reason; show the UUID returned after save so
   a correction can be referenced without exposing patient-row history.
3. Add a distinct `Refresh model` control and show status/progress. Do not
   equate refresh with choosing a prediction month.
4. Add a horizon input and `Calculate survival` control. Query the current
   published model and show survival probability, event probability, counts,
   `D`, `Y`, rate, mean, median, interval method, model/snapshot IDs,
   fit/data-as-of times, and pending-update status.
5. Add aggregate-only `GET /curves/exponential` output for the fitted curve
   and transformed likelihood-ratio rate interval; allow selecting a
   historical fit. Show the curve with pointwise band and aggregate
   Kaplan–Meier overlay. Label axes in months and mark observed follow-up
   range. Add interval probability and a clearly labeled conditional-survival
   calculator that explains constant hazard.
6. Add model history selection/comparison and short documented cache TTLs with
   model-aware keys. Distinguish service down, stale published model, and
   failed candidate; never present stale output as current.
7. Show no raw patient rows, secrets, clinical advice, or fake personalization.
   Use synthetic-only examples.

### Success criteria

- UI tests cover valid/invalid writes and correction metadata, survival horizons, refresh state,
  model history, cache invalidation, API-down messaging, and all visible
  stale/failed states.
- Fixture shows `S(24)=0.4910982295`; P009 scenario shows rate `4/171`;
  historical model outputs remain pinned.
- UI only calls API and displays aggregate outputs; no credentials or raw
  records appear in the browser response.

### Student exercise

Show how longer censored follow-up changes the curve without adding a death.

## M10 — Add CI, security, and operations

### Objective

Automate local quality/security checks and provide safe backup, restore, and
failure investigation workflows.

### Context

Passing scans are evidence, not proof of clinical validity or production
readiness. CI must never deploy or expose secrets from untrusted pull requests.

### Steps

1. Add GitHub Actions for Ruff, formatting, mypy, unit tests, migrations, dbt,
   API/pipeline integration, image build/smoke, and DAG parsing in the pinned
   Airflow image. Use synthetic data, disposable credentials, least-privilege
   tokens, full-SHA action pins, and no secrets for untrusted PR code. Run CI
   on pull requests, pushes, and manual dispatch; do not deploy.
2. Add Gitleaks, pip-audit for all locked project extras/groups, optional
   Trivy, and Dependabot. State whether the separately pinned Airflow image is
   scanned. Do not silently suppress findings; document justified exceptions
   and scanner limitations in this guide.
3. Audit loopback-only host ports, database grants, non-root containers,
   secrets, parameterized SQL, and logs. Logs may contain run/model IDs but
   not raw payloads or credentials; do not claim JSON logging unless it is
   implemented.
4. Add `make security`, `make backup`, `make restore-test`, and a separately
   confirmed `make reset-data`; use ignored local backup directories and an
   isolated scratch database for restore tests.
5. Ensure `down` preserves volumes. Test write authorization, read-role
   restrictions, DB restart, backup restore, and one deliberately failing
   check without creating or changing a PR.
6. Put the threat model and operations runbook in this guide, not separate
   Markdown files.

### Success criteria

- CI executes real checks and does not push, merge, or deploy.
- Secret/permissions/port audits and restore tests pass or have explicit,
  actionable exceptions.
- `reset-data` requires explicit confirmation; ordinary shutdown preserves
  volumes.
- Findings and tool limitations are reported accurately.

### Student exercise

Trace one failure from CI or pipeline logs to its regression test.

## M11 — Verify and teach the complete application

### Objective

Prove the local application works end to end and make this guide sufficient for
a new student or coding agent to reproduce the project.

### Context

Release readiness means verified commands and honest limitations, not a
complete checklist by assertion. No external release is requested.

### Steps

1. In a clean disposable environment, verify setup, fixture ingestion, manual
   refresh, API, dashboard, duplicates, corrections, historical models,
   failed-refresh retention, database restart persistence, backup, and
   restore. Verify a real Airflow run only when the Docker memory preflight
   passes; never seed or reset an existing user database as a substitute.
2. Reconcile package names, commands, ports, verified versions, and environment
   variables in code and this guide.
3. Include a student quickstart, architecture, data dictionary, versions,
   runbook, threat model, statistical assumptions, production gaps, reading
   guide, demo script, exercises, and rubric in this one guide.
4. Demo baseline `4/135`; `S(24)=0.4910982295`; censored P009 yields `4/171`;
   duplicate is unchanged; separate P002 revision 10→16 yields `4/141`.
   Explain censoring, uncertainty, and provenance.
5. List production gaps: scientific validation, privacy/access, availability,
   backups, monitoring, change approval, intended use. Keep optional
   extensions (event-triggered refresh, other survival models, MLflow,
   Prometheus/Grafana) clearly unimplemented.
6. Record exact commands and outputs, known limitations, demo steps, and
   incomplete checks in this guide. Do not tag or commit unless asked.

### Success criteria

- A clean local run reaches the dashboard and returns the fixture predictions.
- Duplicate, revision, history, failure-retention, restart, and restore
  behaviors match the shared contract.
- Every claimed check has a recorded command and actual result; blocked checks
  are named with the reason.
- This remains the only Markdown file in the workspace.

### Student exercise

Run the demo, explain why a censored follow-up contributes person-time but no
event, and name two production gaps that would need addressing before any
real-world use.

## Environment verification record

### Inherited macOS record (historical, not checked in this workspace)

| Tool | Observed value | Status |
|---|---|---|
| Host OS / shell | macOS (`Darwin`) / `/bin/zsh` | Inherited historical claim |
| Python | 3.11.9 | Inherited historical claim |
| curl | 8.7.1 | Inherited historical claim |
| Docker CLI / Engine | 28.3.0 / 27.4.0 | Inherited historical claim |
| Docker Compose | 2.38.1 | Inherited historical claim |
| Docker smoke | `docker run --rm hello-world` and disposable Compose `run --rm` reportedly passed (arm64v8 image) | Inherited historical claim |
| uv | 0.7.19 | Inherited historical claim |
| Make | GNU Make 3.81 | Inherited historical claim |
| Git | 2.54.0 | Inherited historical claim |
| Git worktree | Reportedly not a Git repository | Inherited historical claim |
| Dashboard stack | Streamlit 1.67.0, Altair 6.3.0, pandas 2.3.3; API/dashboard health reportedly passed | Inherited historical claim |
| Security tools | Gitleaks v8.30.1 and pip-audit reportedly passed | Inherited historical claim |

These values were present in the inherited guide. They have not been
independently verified in this workspace and are not evidence about the
current host.

### Current workspace record: WSL2

Recorded 2026-11-22.

| Tool | Observed value | Status |
|---|---|---|
| Host OS / kernel / architecture / shell | WSL2, Linux `6.6.87.2-microsoft-standard-WSL2`, `x86_64`, `/bin/bash` | Verified by host detection |
| Host Python | Python 3.14.4 | Verified; not used for project commands |
| Project Python | Python 3.11.15 from `uv run --locked python -V` | Verified |
| uv | 0.11.9 | Verified |
| Docker CLI / Engine | Docker 29.1.3 / Ubuntu Core 24, `x86_64` | Verified; daemon reachable |
| Docker Compose / memory | 2.40.3+ds1-0ubuntu1 / 7,678,930,944 bytes | Verified |
| Git worktree | Workspace is not a Git repository | Verified |
| Docker smoke | `docker run --rm hello-world` passed for amd64 | Verified |
| Compose configuration | Default and orchestration profiles both pass `docker compose config -q` | Verified |
| Application services | PostgreSQL, API, and dashboard report healthy; ports bind to loopback | Verified |
| Airflow | Pinned Airflow 3.4.0 Python 3.11 image; scheduled DAG run passed; optional services stopped normally | Verified |

No host system packages or global shell settings were changed. Python
dependencies were installed from the three local uv lockfiles. The main
Compose database was newly initialized for this workspace and contains only
the canonical synthetic fixture. PostgreSQL, API, and dashboard remain
running. Airflow containers were stopped with `docker compose stop`; their
named metadata/log volumes were preserved. A separate PostgreSQL test
container bound to `127.0.0.1:55432` is also still running; do not stop it,
because its `--rm` container has an anonymous volume.

## Implementation progress

Update this table after each milestone. Mark a milestone complete only when its
success criteria were actually checked.

| Milestone | Status | Evidence / limitation |
|---|---|---|
| M00 — Environment | Complete for this WSL2 workspace | Verified Linux WSL2 kernel, `x86_64`, `/bin/bash`, host Python 3.14.4, uv-managed project Python 3.11.15, uv 0.11.9, Docker 29.1.3, Compose 2.40.3, and Docker memory 7,678,930,944 bytes. Hello-world, Compose configuration, and app health checks passed. Workspace is not a Git repository; the inherited macOS values above are unverified here. |
| M01 — Package | Complete | Python 3.11 `src/survivallab` package, CLI, strict models, root lock, and dev setup are in place. `make quality` passed: Ruff, formatting, mypy, and 27 tests; 3 PostgreSQL integration tests skip without a test URL. |
| M02 — Synthetic data | Complete | Deterministic fixture/generator, strict observation models, CSV validation, and CLI are implemented. The final unit suite passed; both notebooks executed successfully in fresh kernels. |
| M03 — Likelihood notebook | Complete | Notebook derives the censored likelihood and validates package estimates against alternative computations; it executed successfully with the pinned Python environment. |
| M04 — Statistics | Complete | Statistical tests pass in `make quality`. Baseline `D=4`, `Y=135`, `lambda=4/135`, `S(24)=0.4910982295`; LR interval `[0.0091985194,0.0688318046]`; log-Wald interval `[0.0111203289,0.0789468516]`. Zero events return `not_fitted`. |
| M05 — PostgreSQL | Complete | PostgreSQL 16.4, Alembic, immutable versioned ingestion, snapshots, and least-privilege roles are implemented. Three repository integration tests passed against an isolated database. Fresh Compose migration and rerun passed; reader raw-row access and ingest UPDATE were denied. |
| M06 — dbt | Complete | Separate locked dbt Core 1.12.7/dbt-postgres 1.11.0 environment. A real `dbt build` completed 19 steps: 4 views and 15 data tests. The Dockerfile's directory-copy layout was corrected after the first container refresh found no models. |
| M07 — API/refresh | Complete | Compose API is healthy and publishes the fixture via dbt → fit → validate → publish (`n=8,D=4,Y=135`); `/survival?months=24` returned `0.4910982295021551`. Verified duplicate seed (`8` idempotent), unauthorized write rejection (401), repository idempotency/revisions, P009 `4/171`, failed-candidate retention, and unchanged-refresh skip. PostgreSQL restart preserved the published model and prediction. |
| M08 — Airflow | Complete locally; profile stopped | Pinned Airflow 3.4.0 image/DAG parsed; metadata DB, API, scheduler, DAG processor, and triggerer became healthy. Scheduled DAG runs succeeded and returned unchanged-refresh `skipped` results. Initial attempts exposed a scheduler digest typo and missing shared Airflow JWT signing key; both were fixed. Earlier failed runs remain in metadata history. `make orchestration-down` stopped containers without deleting volumes. |
| M09 — Dashboard | Complete locally; browser write-flow not automated | Six dashboard/client tests pass. Compose dashboard health passed; the integrated browser loaded the SurvivalLab page and its sections, and aggregate curve APIs returned 101 exponential and 5 Kaplan–Meier points. API-down messaging is covered by a test that forces an unavailable endpoint. No browser data-entry/refresh click-through was run. |
| M10 — Hardening | Complete locally; hosted CI not run | Added read-only/no-deploy GitHub Actions, weekly Dependabot for all three Python locks and actions, dependency audits, Gitleaks, backup/restore, and confirmation-gated reset. `make security` passed for root, dbt, and Airflow locks (no known vulnerabilities) and local source scan (no leaks). Backup restore verified 6 application tables and 8 observations. Reset refused without `CONFIRM_RESET=YES`; no destructive reset was run. Workflow YAML parsed locally; GitHub Actions could not run because no Git repository/remote exists. Trivy is not configured. |
| M11 — Release/teaching | Complete locally; GitHub-hosted CI unavailable | Quickstart, architecture, demo, data dictionary, operations/threat model, rubric, production gaps, and verified commands are recorded below. The default stack is running and survives a database restart. Hosted CI and a browser-driven write flow remain unverified; no commit, push, or deployment was performed. |

## Student quickstart

This is a local synthetic-data teaching application, not a clinical service.
Docker Compose binds the API, dashboard, and PostgreSQL host ports to loopback.
Use Docker Desktop with enough memory for the services you enable. The optional
Airflow profile requires at least 4 GiB according to its preflight. In this
WSL2 workspace, all Airflow services became healthy at 7,678,930,944 bytes of
Docker memory and scheduled refresh runs succeeded; the profile is currently
stopped with its volumes preserved.

```sh
make init-local-secrets
make up
# On a new, empty database only:
make seed-fixture
make refresh
```

Open [http://localhost:8501](http://localhost:8501). The dashboard calls
FastAPI; it has no database connection. `make up` applies migrations and
starts PostgreSQL, API, and dashboard. Do not run `make seed-fixture` against an existing database without first
checking its contents and understanding any conflicts. This workspace has a
newly initialized Compose database containing the canonical eight-row
synthetic fixture; a second seed returned eight idempotent observations.
`make init-local-secrets` refuses to overwrite the existing mode-600 `.env`.

Useful checks:

```sh
make quality
make test
make test-dashboard
make test-integration
make security
make status
```

The optional Airflow UI is bound to
[http://localhost:8081](http://localhost:8081); it remains outside default
startup and is stopped in this workspace. The standard `make orchestration-up`
target requires Docker memory of at least 4 GiB. Normal shutdown preserves
database and Airflow metadata volumes:

```sh
make orchestration-down  # only if the optional profile was started
make down
```

Back up before maintenance. `make backup` writes a mode-600 custom-format
dump under the ignored `backups/` directory. Test a chosen dump with
`make restore-test BACKUP=backups/<dump-name>.dump`; it restores to a uniquely
named scratch database on the current PostgreSQL service, checks application
table and observation counts, then drops only that scratch database. To
intentionally clear the local application tables, first make a backup and
then run `make reset-data CONFIRM_RESET=YES`. The destructive confirmed reset
was not run in this workspace.

## Architecture and data dictionary

The end-to-end path is:

1. The dashboard sends versioned follow-up observations to `POST /observations`.
2. PostgreSQL stores immutable observation versions. A snapshot pins the
   latest valid version per synthetic patient.
3. dbt validates snapshot membership and calculates `n`, `D`, and `Y`.
4. The API pipeline checks dbt/Python totals, fits the exponential model, and
   atomically publishes a candidate. Failed checks leave the previous
   published fit active.
5. FastAPI exposes aggregate model/history/prediction/curve responses.
   Optional Airflow calls the same authenticated refresh endpoint.

The full contract and formulas are in [Shared project contract](#shared-project-contract)
and the row-level CSV fields are in [M02 data dictionary](#m02-data-dictionary).
In short:

| Field/statistic | Meaning |
|---|---|
| `patient_id` | Synthetic identifier; never displayed in aggregate predictions |
| `version` | Positive append-only revision number |
| `duration_months` | Observed follow-up, including censored follow-up |
| `event_observed` | Integer `1` for the event, `0` for right-censoring |
| `n` | Number of patients in the immutable snapshot |
| `D` | Sum of observed events |
| `Y` | Sum of observed person-time in months |
| `lambda_hat` | Exponential MLE `D/Y`, fitted only when `D > 0` |
| `S(t)` | Exponential survival `exp(-lambda_hat * t)` |

The dashboard's exponential interval band transforms the likelihood-ratio
interval for the rate at each plotted time; it is not a simultaneous band.
Kaplan–Meier is an aggregate empirical diagnostic. The conditional calculator
assumes a constant hazard. Neither result is individualized.

## Demonstration script

Use a disposable database initialized with the canonical eight-row synthetic
fixture. Baseline aggregates are `n=8`, `D=4`, and `Y=135`.

1. In the dashboard, enter 24 months and calculate survival. The API returns
   `exp(-24 * 4/135) = 0.4910982295`.
2. Explain that an observed event contributes to both `D` and `Y`; censored
   follow-up contributes to `Y` only.
3. Add a new synthetic patient P009, version 1, duration 36 months, event
   **No**. The saved update marks the published model stale; the survival
   month input did not trigger a refresh.
4. Select `Refresh model`. The new snapshot has `n=9`, `D=4`, `Y=171`, so
   `lambda_hat=4/171`. The 24-month prediction uses that new rate. The
   previous model remains available in history with its original `4/135` fit.
5. Submit the same P009 version again. The API reports an idempotent retry;
   it does not add another row or change the aggregate.
6. Compare the exponential curve and transformed rate interval with the
   aggregate Kaplan–Meier curve. Try interval probability and conditional
   survival, and point out the constant-hazard assumption.
7. In the separate integration-test exercise, revise P002 from 10 to 16
   months using a new version and correction metadata. The latest-version
   snapshot changes `Y` from 135 to 141 while `D` remains 4, yielding `4/141`;
   historical fits remain unchanged. The dashboard shows the observation UUID
   returned on save so a user can reference a correction without listing raw
   patient rows.

Run the P009 and P002 scenarios separately from the clean baseline; do not
apply both and assume either expected denominator. The main database in this
workspace already has user-owned contents and must not be reset or reseeded.

## Operations runbook and threat model

### Assets and trust boundaries

- Assets: local `.env` credentials, raw synthetic observations, immutable
  snapshots, published-model history, and local backup dumps.
- The browser talks to Streamlit; Streamlit holds the API write key server-side
  and sends requests to FastAPI over the Compose network. The browser does not
  receive the key.
- FastAPI uses separate ingest, pipeline, and reader database roles.
  PostgreSQL ports and app ports bind to `127.0.0.1`; changing that binding
  would expose this demo to other machines.
- Airflow has a separate metadata database and only calls the authenticated
  refresh API. It does not own patient data or fit logic.

### Controls and limitations

- `.env` is ignored, created with restrictive permissions, and excluded from
  Docker build contexts. Never print it, commit it, or send backups to a
  third party.
- The API key is a single local shared secret. Read endpoints are unauthenticated
  on the loopback-bound demo API; do not expose this service publicly.
- SQL uses bound parameters. API and pipeline logs record exception types and
  operational model/run IDs, not request payloads or credentials. Logging is
  safe contextual text, not structured JSON.
- API and dashboard containers run as non-root, read-only containers with
  dropped capabilities. Database roles are least-privilege for this demo.
- Backup dumps contain the database's row-level contents and are not encrypted
  or off-site. Protect them as sensitive data; this setup is not a production
  backup strategy.
- `make security` runs `pip-audit` against all root extras/groups and the
  separate dbt and Airflow locks, plus Gitleaks v8.30.1 pinned by image digest.
  In a Git worktree, Gitleaks scans Git history; in this non-Git workspace,
  its local config excludes only `.env` and generated environments/caches.
  All three dependency audits reported no known vulnerabilities; the local
  project itself is excluded because it is not a published package. Trivy
  image scanning is not configured or claimed here.
- GitHub Actions has read-only repository permissions, no deployment steps,
  and no repository secrets. It generates disposable local credentials in
  the job. The current workspace has no Git repository or remote, so the
  workflow has not been run on GitHub.

### Recovery and investigation

1. `make status` shows aggregate model/pipeline status; inspect service state
   with `docker compose ps`.
2. On refresh failure, inspect the pipeline `error_code`, the dbt/data-quality
   result, and the matching regression test. The active fit is retained on
   candidate failure.
3. `make backup` saves a custom-format dump in ignored `backups/`. It backs up
   the currently configured Compose database; review that target before using
   it with any database containing non-synthetic data.
4. `make restore-test BACKUP=...` restores into a unique scratch database on
   the same PostgreSQL service, verifies all six application tables and the
   observation count, then drops only that scratch database. This workspace
   verified six tables and eight fixture observations; the mode-600 dump
   remains in ignored `backups/verification.dump`.
5. `make down` preserves the primary PostgreSQL volume. `make reset-data`
   requires the exact `CONFIRM_RESET=YES`; this is destructive and was tested
   only for refusal without confirmation here.

## Reading guide and grading rubric

Suggested order: work through M00–M11 in sequence; then inspect
`notebooks/02_likelihood.ipynb`, the exponential statistics module,
`dbt/models/`, `src/survivallab/pipeline.py`,
`src/survivallab/api.py`, and `src/survivallab/dashboard.py`. Finish with the
unit and integration tests. Each milestone includes a short exercise; use the
demonstration script above to connect the formulas, snapshot versions, API,
and visible stale-model state.

| Area | Points | Evidence |
|---|---:|---|
| Survival statistics and uncertainty | 25 | Derive the censored likelihood, calculate `D/Y`, survival, median, and explain the interval |
| Data quality and provenance | 20 | Explain append-only versions, latest-version snapshots, dbt checks, and historical fits |
| API and interface | 20 | Use separate save/refresh/predict actions; interpret curves and stale/failed states |
| Tests and reproducibility | 20 | Run focused unit, UI, integration, security, and restore checks; explain one regression |
| Operations and safety | 15 | Protect credentials/backups, respect reset confirmation, explain limitations and threat boundaries |

**Total: 100 points.** A passing project should score at least 70 and must
earn points in both statistics and safety; a visually polished dashboard
cannot compensate for incorrect censoring or unsafe data handling.
