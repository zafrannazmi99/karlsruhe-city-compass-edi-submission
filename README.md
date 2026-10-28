# Karlsruhe City Compass

Karlsruhe City Compass is a small AI city guide. Choose a focus category, optionally share the browser's location, and ask for a place in natural language. The app retrieves matching OpenStreetMap (OSM) records and tries to verify candidates against the live OSM Overpass API in bounded batches. Mistral selects among live-confirmed places; if Overpass is unreachable, the app may use a recent local snapshot with an explicit not-live-verified status and a deterministic answer. The React site displays the starting point, results, source details, and walking route on a map. The CLI uses the same search and verification pipeline.

## What the project demonstrates

- **Environment setup:** Python virtual environment, Node.js frontend, Docker Desktop, and a private `.env` file.
- **Document ingestion:** download Karlsruhe OSM features or import a local Overpass JSON export; normalize each mapped feature into searchable text with source tags and coordinates.
- **Chunking and embeddings:** LlamaIndex `SentenceSplitter` uses 512-token chunks with 50-token overlap; `all-MiniLM-L6-v2` creates 384-dimensional local embeddings.
- **Vector database:** PyMilvus `MilvusClient` stores text, 384-dimensional vectors, and JSON place metadata in the `karlsruhe_places` Milvus collection. Embeddings are normalized, and exact inner-product search ranks them by cosine similarity.
- **RAG and verification loop:** explicit place intent in the user's prompt determines a strict place-type filter; the focus chip is used when the prompt does not name a type. Milvus ranks the original question without category text being prepended. A bounded live Overpass loop confirms candidate IDs and current categories, drops removed, closed-tagged, or reclassified objects, and refills the shortlist. If Overpass is unreachable, results from a local OSM snapshot are shown only when the dataset is at most 14 days old and are explicitly labelled not live-verified. Mistral selects candidate IDs; deterministic code renders every displayed place fact from OSM tags.
- **Route view:** browser geolocation requires an explicit user click and permission. The app requests a walking itinerary from the OpenStreetMap foot router and draws its returned street/path geometry, distance, and duration on MapLibre GL JS. If that router is unavailable, the UI says it is showing straight-line estimates instead.
- **Comparable place facts:** every result card separates straight-line distance from route-leg distance and displays OSM-tagged hours, wheelchair access, outdoor seating, entrance information, and website links. Missing OSM values are labelled “Not listed”; a live map record does not establish opening status.
- **Category filters:** the website can focus retrieval on cafes, restaurants, playgrounds, schools and universities, libraries, healthcare, transit, sports, public services, places to stay, fishing areas, museums, attractions, parks, water features, or shopping. The filter is applied in Milvus against the normalized place type.
- **Website and CLI:** FastAPI serves the web UI; `python -m app.cli` runs ingestion, indexing, single questions, and five evaluation prompts.
- **Saved trips:** optional local accounts let users collect selected places into trips. Passwords are hashed and trip data is user-scoped in SQLite.

## Requirements

- Windows 10/11 with Docker Desktop using its WSL 2 Linux engine
- Python 3.12
- Node.js LTS with npm
- Ollama reachable from the backend, with `mistral:7b` available (or a compatible Mistral tag)
- Internet access for the first Python/npm installation, live OpenStreetMap verification, OSM data retrieval, and model downloads

Milvus runs in Docker. The Python virtual environment and embedding model run on your laptop. If the Mistral host is remote, keep it on a trusted private network or behind a protected tunnel; do not expose Ollama directly to the public internet.

## Step 1: Configure the private settings

Open PowerShell in the project root. If `.env` does not exist yet, create it from the template:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Open `.env` in a text editor. Set a random `SECRET_KEY`, a reachable `OLLAMA_BASE_URL`, and the model name. The Milvus, model, and chunk settings already have local defaults in `.env.example`. Do not commit `.env`; Git ignores it.

To create a signing secret, run:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

If you use Ollama locally, install/start Ollama, then run `ollama pull mistral:7b`. Set `OLLAMA_BASE_URL=http://localhost:11434`. For an existing private Mistral server, keep its private address in `.env` instead.

## Step 2: Start Milvus

Open Docker Desktop and wait until its status says the engine is running. Open a PowerShell terminal in the project root and run:

```powershell
.\milvus\start.ps1
```

The script downloads the official Milvus 2.6.25 standalone Compose file the first time, then starts the Milvus services. This matches the PyMilvus 2.6 SDK range used by the project. The local endpoint is `http://localhost:19530`; the optional Milvus Web UI is `http://localhost:9091/webui/`. Milvus data stays under `milvus/volumes/`. To stop the services later while keeping their data:

```powershell
.\milvus\stop.ps1
```

## Step 3: Install Python packages

Python environments are local to each computer and are not included in this repository. From the project root, create a Python 3.12 environment and install the backend packages:

```powershell
py -3.12 -m venv backend\.venv
.\backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

The first install and first embedding-model download take longer than later runs.

## Step 4: Download and index places

Run these commands from the project root:

```powershell
Push-Location backend
.\.venv\Scripts\python.exe -m app.cli ingest
.\.venv\Scripts\python.exe -m app.cli index
Pop-Location
```

The importer requests education (schools, colleges, universities, kindergartens, and campuses), libraries, healthcare, transit, sports and recreation, public services, accommodation, food, shopping, attractions, and outdoor places inside a Karlsruhe-focused bounding box. It tries Overpass first and Photon as a smaller fallback. If Photon is needed, it merges new results into the existing snapshot so a partial lookup cannot delete the larger dataset; it also keeps the older snapshot date so the app does not present old places as recently refreshed. Raw source JSON goes to `data/raw/karlsruhe_places.json`; normalized place records go to `data/places.json`; source and freshness information go to `data/places_metadata.json`. The CLI prints education, healthcare, library, and transit counts after ingestion so you can see whether the expanded types arrived. The index command creates and splits LlamaIndex documents, generates local embeddings, and uses PyMilvus `MilvusClient` to replace the configured collection. After changing ingestion categories, run both ingest and index once. Generated source data and local databases are ignored by Git.

Run this from the project root to refresh the local data and then Milvus:

```powershell
Push-Location backend
.\.venv\Scripts\python.exe -m app.cli ingest
.\.venv\Scripts\python.exe -m app.cli index
Pop-Location
```

You only need to repeat these commands when you want to refresh or expand the indexed OSM data. The website and CLI can only answer location questions about places present in this Karlsruhe dataset; OSM coverage and place details are incomplete, and this is not a general-purpose answer bot.

To import an Overpass export saved on your computer, run this from `backend`:

```powershell
.\.venv\Scripts\python.exe -m app.cli ingest --file "C:\path\to\karlsruhe-overpass.json"
.\.venv\Scripts\python.exe -m app.cli index
```

OSM coverage is incomplete and tags may be sparse. A missing tag means the app cannot verify that detail. Check opening hours, accessibility, specific products, and facilities against the linked source records.

## Step 5: Run the API and website

Open a PowerShell terminal in the project root, then start the API:

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

The API is at `http://127.0.0.1:8000`; its interactive API docs are at `http://127.0.0.1:8000/docs`.

Open a second PowerShell terminal in the project root and start the website:

```powershell
Set-Location frontend
npm.cmd install
npm.cmd run dev
```

Open the local URL printed by Vite (normally `http://127.0.0.1:5173`). Do not open `frontend/index.html` directly; React must be served by Vite over HTTP.

## Step 6: Use the CLI

From a terminal in `backend`, run:

```powershell
.\.venv\Scripts\python.exe -m app.cli --help
.\.venv\Scripts\python.exe -m app.cli ask "Find a cafe near me" --origin "49.0093, 8.4020"
.\.venv\Scripts\python.exe -m app.cli ask "Where can I buy a washing machine?" --origin "Europaplatz, Karlsruhe" --json
```

Each answer prints the retrieved contexts, semantic scores, source links, route-leg distances, the suggested route total, and the record-grounded response. Mistral selects place IDs; application code writes the final answer from the selected OSM records. Use `--json` to save the complete response in a script or pipe it elsewhere. An origin can be a Karlsruhe place name or `latitude, longitude`; if omitted, the city centre is used.

## Five evaluation examples

After Milvus has been indexed and Mistral is configured, run these five scenarios and save the actual retrieved contexts and generated answers:

```powershell
.\.venv\Scripts\python.exe -m app.cli demo --output ..\examples\demo_results.json
```

The saved JSON contains each original question, starting point, retrieved OSM contexts, route geometry and distance, final answer, and model status. The checked-in file is a real CLI run covering restaurants, family activities, appliance shopping, cafes, and an outdoor multi-stop route. Results vary as OSM data changes, so generate a fresh report before a live demonstration if you have refreshed the local index.

## API overview

- `POST /ask` — retrieve, rerank by location, prepare a route, and generate an answer.
- `POST /search` — return semantically relevant places and their estimated visit order without LLM generation.
- `GET /health` — basic API and configured model status.
- `POST /auth/register`, `POST /auth/login`, `GET /auth/me` — local account routes.
- `GET /trips`, `POST /trips`, `POST /trips/{trip_id}/places`, `DELETE /trips/{trip_id}` — saved trips.

Example request:

```json
{
  "question": "Find a sushi restaurant near me",
  "limit": 5,
  "origin": "49.0093, 8.4020"
}
```

## Evaluation notes and limitations

- Place names, coordinates, categories, and optional details come from OSM. The system does not know current inventory, ratings, or live opening status unless a record contains that data.
- Every recommendation shown by the website is checked against a live OpenStreetMap Overpass response. The loop checks at most 20 candidates per search in batches of five, skips missing, closed-tagged, or reclassified objects, and continues through the Milvus-ranked list until it fills the requested limit. If the live source is unavailable, the app does not present cached candidates as verified. An existing OSM object does not prove that a venue is open or accepting visitors.
- Explicit category intent in the question takes priority over the focus chip. The selected focus is applied when the question does not name a category. Milvus first ranks the user's original wording; proximity is used afterward to arrange the verified shortlist into a route.
- The data index currently covers Karlsruhe. Browser GPS can show a location elsewhere, but recommendations are limited to the indexed Karlsruhe area.
- Route order uses a greedy nearest-next-stop heuristic, not a globally optimal traveling-salesperson solver.
- Distances are great-circle estimates, and the map line connects stops directly. There are no pedestrian turn instructions or travel-time estimates.
- Mistral can only select IDs already retrieved by Milvus; application code renders facts from a whitelist of OSM fields. This prevents the model from inventing hours, amenities, or shop inventory. If Ollama is offline or slow, retrieval and a deterministic shortlist still work. The default Ollama request timeout is five minutes for a cold local model and can be changed with `OLLAMA_REQUEST_TIMEOUT_SECONDS`.
- A useful next improvement is hybrid semantic + keyword search for exact cuisine and product terms, a retrieval evaluation set, and a pedestrian-routing service.

## Sources and attribution

OSM map/place data are © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright) and available under the [Open Database License](https://opendatacommons.org/licenses/odbl/). The app links each place card to its OSM object.

The map uses the [CARTO Voyager basemap style](https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json) with MapLibre GL JS. MapLibre displays the basemap attribution in the map controls; the style and its vector tiles need an internet connection.

Milvus Windows setup follows the [official Milvus 2.6 Windows Docker guide](https://milvus.io/docs/v2.6.x/install_standalone-windows.md). LlamaIndex provides the document and embedding pipeline, while the [PyMilvus client API](https://milvus.io/api-reference/pymilvus/v2.6.x/About.md) stores and searches vectors using Milvus's supported client interface. The [local models guide](https://docs.llamaindex.ai/en/v0.10.22/getting_started/starter_example_local/) documents the Ollama integration pattern.
