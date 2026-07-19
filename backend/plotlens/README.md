# PlotLens — backend (compute engine + data layer)

The defensible core of PlotLens: takes a coordinate, computes **plot-specific
terrain artifacts** that an LLM prompt cannot reproduce (because they require the
actual elevation grid for that polygon), and renders them into a shareable image.

## What's here (and runs today)

```
plotlens/
  data/dem.py        DEM providers: Synthetic, SRTM(OpenTopography), Cached
  data/osm.py        OSM providers: Synthetic, Overpass(live), Cached
  engine/terrain.py  contours, slope, relative elevation, D8 flow accumulation
  engine/access.py   nearest road/water/transit/emergency, adjacency
  render/artifact.py terrain artifact PNG (contours + flow)
  render/rings.py    distance-rings artifact PNG (access & surroundings)
  pipeline.py        coordinate in -> 2 artifacts + metrics out
cache/               tile + OSM cache (auto-created)
out/                 generated artifacts
```

Run it:

```bash
PYTHONPATH=. python3 plotlens/pipeline.py
```

Produces three reports (filled-pond, riverside, upland) and proves the engine
discriminates between them. Re-running any coordinate hits the cache.

## The one-line deploy swap

Everything runs now on a **synthetic DEM** (no network needed). To go live with
real Copernicus/SRTM elevation, change ONE call in `pipeline.build_provider`:

```python
# dev (here):
inner = SyntheticDEM(archetype=archetype)
# production:
inner = SRTMProvider(api_key=OPENTOPO_KEY)   # needs rasterio + network
```

The DEM, OSM, engines, renderers, cache, and pipeline are untouched. That
isolation is the whole point of the provider interfaces.

## What's real vs. stubbed

REAL and tested here:
- D8 flow accumulation, slope, relative-elevation, drainage bearing
- nearest-feature distances, adjacency, transparent access classifier
- disk cache for BOTH layers (keyed by rounded coords)
- both render pipelines (terrain artifact + distance-rings artifact)

STUBBED for deployment (network/rasterio needed, unavailable in sandbox):
- `SRTMProvider.fetch` — OpenTopography API, import-guarded
- `OverpassProvider.fetch` — live OSM Overpass query, import-guarded
- imagery (Sentinel-2 then-vs-now) — add as a sibling provider, same pattern

## Next build steps (not done yet)
1. `data/imagery.py` (Sentinel-2): then-vs-now + NDWI change number.
2. Wrap `pipeline.run_report` in a FastAPI endpoint + job queue.
3. PDF assembly: compose both artifacts + 8-category readings into one document.
4. Payment + unlock gating on the frontend.

## Honest limits (keep these visible to users)
- 30 m elevation resolution = contextual reads ("plot sits in a dip"), not
  survey-grade. A small plot is only a few pixels.
- Flow accumulation ignores storm drains, culverts, upstream dams.
- Output is **indicative**, never a guarantee or a substitute for a site survey,
  soil test, or legal title check.
