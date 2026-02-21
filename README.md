# Sargassum to Methane Model (Miami)

Interactive, config-driven model for converting sargassum into methane through a gasification + methanation pathway (no anaerobic-digestion pathway), with two business options:

- `onsite_energy`: build and operate your own conversion system.
- `existing_facility`: use third-party processing infrastructure.

The model can run one mode or compare both automatically and select the best daily profit case.

## What you can edit quickly

Main editable file:

- `config/model_config.yaml`

You can modify feedstock, process, economics, optimization bounds, and whether live Miami data pulls are enabled.
The model is explicitly enforced as `project.conversion_path: gasification_methanation`.

## Miami-area data integration

The model attempts to pull:

- Florida industrial gas price benchmark (EIA API endpoint).
- Miami temperature conditions (NOAA station data).

If a live pull fails, the model automatically uses fallback values from `model_config.yaml`.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration modes

- `app.basic_cost_mode: true` keeps CAPEX, financing, and tax effects disabled for simple operating-cost analysis.
- Set `app.basic_cost_mode: false` if you want full TEA-style CAPEX/tax economics.
- All user input is normalized via config validation at runtime to prevent bad-value crashes.

## Authentication

- App login is enabled through `app.auth` in `config/model_config.yaml`.
- Allowed users are configured as a list.
- Password is read from environment variable `APP_PASSWORD` if present.
- If `APP_PASSWORD` is not set, the app uses `app.auth.default_password`.
- User settings are auto-saved per login to `data/user_settings/<username>.yaml`.
- On next login, that user's saved settings are loaded automatically.

## Run command-line model

```bash
python -m src.sargassum_model.run_model --config config/model_config.yaml --out outputs
```

Outputs are written to:

- `outputs/results.json`
- `data/raw/miami_data_cache.json`

## Run interactive dashboard

```bash
streamlit run app.py
```

Dashboard features:

- live parameter controls in sidebar
- mode comparison chart + table
- profit waterfall
- optimization results per mode
- sensitivity tornado chart
- save current UI controls back to `config/model_config.yaml`
- expanded TEA-style cost and revenue accounting in waterfall and outputs:
  - utilities (electricity, drying thermal, water)
  - labor, maintenance, insurance, admin
  - catalyst/chemicals, ash disposal
  - financing and annualized CAPEX
  - renewable premium, carbon credits, and char byproduct sales
  - policy levers: production tax credits, investment tax credits, and tax-cut effect on income tax
- new `Pyrolysis + Biochar` tab with:
  - biochar, bio-oil, and syngas output estimates
  - pyrolysis-specific revenue and cost model
  - biochar-focused profit waterfall and economics table

## Production deployment (GitHub-ready)

This repo now includes:

- `Procfile` for PaaS platforms.
- `runtime.txt` pinning Python runtime.
- `Dockerfile` and `.dockerignore` for container deployment.
- `.streamlit/config.toml` for server settings.
- `.github/workflows/ci.yml` for automatic GitHub CI smoke tests.
- pinned dependencies in `requirements.txt`.

### Deploy from GitHub (Streamlit Community Cloud)

1. Push this repo to GitHub.
2. In Streamlit Community Cloud, click **New app**.
3. Select repo/branch and set entrypoint to `app.py`.
4. Deploy.

### Deploy from GitHub (Render/Railway/Fly/any Docker host)

Use the included `Dockerfile`. Platform should run:

```bash
streamlit run app.py --server.address=0.0.0.0 --server.port=$PORT
```

### Local production-like run

```bash
make install
make smoke
make run
```

## Notes on assumptions

This is a practical decision-support model, not a full first-principles reactor simulator. Keep tuning assumptions in `model_config.yaml` as you refine lab/pilot data.

