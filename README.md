# SurvivalLab

SurvivalLab is a local teaching application for exponential-survival analysis.
It uses synthetic patient records only and is **not** a clinical predictor or
medical advice tool.

The application demonstrates:

- maximum-likelihood estimation with right-censored observations;
- append-only patient versions and immutable analysis snapshots;
- PostgreSQL migrations and dbt data checks;
- a FastAPI refresh pipeline;
- an aggregate-only Streamlit dashboard; and
- optional Airflow 3 scheduling.

## 1. Requirements

Install these tools before starting:

| Tool | Purpose |
|---|---|
| Docker Desktop or Docker Engine | Runs PostgreSQL and the application |
| Docker Compose v2 | Starts the local services |
| `uv` | Manages Python 3.11 and locked dependencies |
| Make | Runs the documented project commands |
| Git | Downloads and updates the repository |
| OpenSSL | Generates ignored local development credentials |

Use Docker Desktop on macOS or Windows/WSL. Use Docker Desktop or Docker
Engine on Linux. The project requires Python 3.11 even though no host Python
installation is needed for the Docker-based application.

Check the tools:

```sh
git --version
make --version
uv --version
docker --version
docker compose version
docker info
```

If Python 3.11 is not available through `uv`, install and select it with:

```sh
uv python install 3.11
uv python pin 3.11
```

## 2. Download the repository

Clone the repository and enter it:

```sh
git clone <REPOSITORY_URL>
cd prepare_class
```

If you downloaded a ZIP, unzip it and open a terminal in the extracted folder.
The terminal must be in the folder containing `Makefile`,
`compose.yaml`, and `SURVIVALLAB_BUILD_PROMPTS.md`.

For an existing directory with no Git remote, no Git remote is required.

## 3. Start the application

From the project directory:

```sh
make doctor
make init-local-secrets
make setup
make up
```

What these commands do:

- `make doctor` reports OS, shell, uv, Python, Docker, and Compose availability.
- `make init-local-secrets` creates an ignored `.env` file with local credentials.
  It refuses to overwrite an existing `.env`.
- `make setup` installs the Python application and development dependencies
  from the lockfile.
- `make up` builds and starts PostgreSQL, FastAPI, and Streamlit.

Wait until all services are healthy:

```sh
docker compose ps
```

Open:

- Dashboard: http://127.0.0.1:8501
- API documentation: http://127.0.0.1:8000/docs
- API health: http://127.0.0.1:8000/health/ready

## 4. Load the synthetic fixture

Run the fixture step only in an empty database:

```sh
make seed-fixture
make refresh
```

Do not seed or reset a database that contains work you want to keep. Existing
data is not overwritten, and `make seed-fixture` will report version conflicts
if the canonical fixture already exists.

The fixture has eight patients, four observed events, and 135 follow-up months.
At 24 months, the published result should have survival approximately:

```text
0.4910982295
```

Check the live status and prediction:

```sh
make status
curl --fail --silent 'http://127.0.0.1:8000/survival?months=24'
```

## 5. Explore the dashboard

At http://127.0.0.1:8501:

1. Enter a synthetic patient ID, version, follow-up months, and event status.
2. Choose **Save observation** to add or revise an observation.
   This does not automatically fit a model.
3. Choose **Refresh model** to create a new published snapshot.
4. Enter a horizon and choose **Calculate survival** to use the current
   published model.
5. Compare model history, the exponential curve, the Kaplan-Meier overlay,
   interval probability, and conditional survival.

The browser receives only aggregate model data. Raw patient observations are
not displayed.

## 6. Explore with the API

Useful read endpoints:

```sh
curl --fail --silent http://127.0.0.1:8000/health/live
curl --fail --silent http://127.0.0.1:8000/health/ready
curl --fail --silent http://127.0.0.1:8000/models/latest
curl --fail --silent 'http://127.0.0.1:8000/survival?months=24'
curl --fail --silent 'http://127.0.0.1:8000/curves/exponential'
curl --fail --silent http://127.0.0.1:8000/models/history
```

Interactive Swagger documentation is available at
http://127.0.0.1:8000/docs.

Refresh, which is a protected write operation, is run with:

```sh
make refresh
```

## 7. Explore the code

A useful reading and testing order:

| Area | Path |
|---|---|
| Statistical implementation | `src/survivallab/stats.py` |
| Synthetic data and validation | `src/survivallab/data.py` |
| Pydantic observation model | `src/survivallab/models.py` |
| Database repository | `src/survivallab/db/` |
| Refresh pipeline | `src/survivallab/pipeline.py` |
| FastAPI application | `src/survivallab/api.py` |
| Streamlit dashboard | `src/survivallab/dashboard.py` |
| dbt models and tests | `dbt/models/` |
| Unit and API tests | `tests/` |
| Statistical notebooks | `notebooks/` |
| Project specification | `SURVIVALLAB_BUILD_PROMPTS.md` |

Try the command-line tools:

```sh
uv run --locked --extra dev survivallab --help
uv run --locked --extra dev survivallab --version
uv run --locked --extra dev survivallab fit-csv data/observed.csv
uv run --locked --extra dev survivallab generate --seed 42 --size 100 --output data/generated
```

Run the statistical and web tests:

```sh
make test
make test-dashboard
make quality
```

Database integration tests require a disposable database URL:

```sh
SURVIVALLAB_TEST_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@127.0.0.1:5432/DATABASE \
  make test-integration
```

Use a database created only for testing. Do not point the integration target at
data you need to keep.

## 8. macOS and WSL notes

macOS:

- Start Docker Desktop and wait until its engine is available.
- Install `uv`, Make, and Git with your normal package manager or platform
  installer.
- Run commands in a POSIX shell from the repository root.

WSL:

- Prefer running Docker Desktop with WSL integration enabled.
- Open and run the repository inside WSL, not through Windows paths.
- Run the commands shown above inside the WSL shell.
- Do not expose PostgreSQL or application ports beyond loopback.

Native Linux:

- Start Docker Engine and ensure the current user can run Docker commands.
- Install Make and `uv` using the distribution package manager or the uv
  installer.

Run `make doctor` to record the detected host and shell.

## 9. Stop or preserve the application

Stop services while preserving PostgreSQL and Airflow volumes:

```sh
make down
```

Restart the same local data later:

```sh
make up
```

Back up the local database:

```sh
make backup
```

To test a backup, pass a generated dump to the restore test:

```sh
make restore-test BACKUP=backups/<dump-name>.dump
```

The restore target uses an isolated scratch database and removes its scratch
volume.

Clearing application data is destructive and requires explicit confirmation:

```sh
make reset-data CONFIRM_RESET=YES
```

## 10. Optional Airflow

Airflow is not part of normal startup. It requires at least 4 GiB of Docker
memory for the standard project safety check:

```sh
make orchestration-up
make orchestration-status
```

The optional Airflow UI is at http://127.0.0.1:8081. Stop it with:

```sh
make orchestration-down
```

The normal API and dashboard remain usable if Airflow is stopped.

## 11. Troubleshooting

No services start:

```sh
make doctor
docker info
docker compose ps
docker compose logs db api dashboard
```

No valid model:

```sh
make seed-fixture
make refresh
make status
```

An existing `.env` prevents secret initialization:

- Confirm it belongs to this repository and contains local synthetic credentials.
- Back it up before changing or replacing it.
- `make init-local-secrets` intentionally refuses to overwrite it.

Keep credentials private. Do not publish `.env`, database dumps, or logs.

## Scope and limitations

This project is a reproducible local teaching system. It has not established
scientific, clinical, privacy, availability, backup, or production readiness.
Passing tests and security scans do not make the model clinically valid.
