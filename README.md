# CVND

## First-time setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Earth Engine authentication

```bash
earthengine authenticate
```

## Environment variables

```bash
cp .env.example .env
```

Edit `.env` and set your Google Earth Engine project ID:

```env
GEE_PROJECT_ID=your-gee-project-id
```

Find your project ID at https://code.earthengine.google.com/

## Run pipeline

```bash
./scripts/run_pipeline.sh
```
