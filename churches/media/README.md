# Church exterior media + manual additions

## Remove or correct a bad pin

Edit `data/raw/overrides.csv`:

```csv
action,osm_id,assessor_objectid,match_name,match_address,notes
exclude,,1647442,HOUSE OF ISRAEL,411 MARKET,Non-Christian
exclude,358997038,,PARK PLACE,,Wrong map location
```

Then re-run `python3 normalize_churches.py`.

## Add a church you found in the field

Edit `data/raw/enrichment.csv`. For a **new** church, leave `church_id` and `osm_id` blank and provide coordinates:

```csv
church_id,osm_id,assessor_objectid,name,denomination,denomination_raw,year_founded,address,lat,lon,shot_status,photo_url,notes
,,,Grace Chapel,Baptist,,1998,412 Oak St,34.50812,-93.05234,pending,./media/grace-chapel.jpg,Found while filming on Oak St
```

Get coordinates from Google Maps (right-click → copy coordinates) or your phone's GPS.

## Update an existing church

Use its `church_id` (from the map popup), `osm_id`, or `assessor_objectid` (most stable across rebuilds):

```csv
church_id,osm_id,assessor_objectid,name,denomination,denomination_raw,year_founded,address,lat,lon,shot_status,photo_url,notes
hs-0012,,,,,,,,filmed,./media/hs-0012.jpg,Exterior filmed 2026-07-07
```

## Mark filmed from the dashboard (easiest for batches)

1. Open `churches/index.html`.
2. In the church list, **check the box** next to each church you’ve filmed (or use **Mark filmed** in the map popup).
3. Click **Download filmed rows (enrichment.csv)** in the Fieldwork Checkoff panel.
4. Open the downloaded file and append those rows into `data/raw/enrichment.csv` (don’t replace existing photo rows).
5. Run `python3 normalize_churches.py` and reload the map.

Checks save in your browser until you clear them. Photos are optional at this stage — you can add `photo_url` later.

## Mark filmed + add popup photo (manual)

1. Save the image under `media/` (e.g. `media/CentralBaptistChurch.JPG`).
2. Add a row to `enrichment.csv` with `shot_status=filmed` and `photo_url` relative to `index.html`:

```csv
church_id,osm_id,assessor_objectid,name,denomination,denomination_raw,year_founded,address,lat,lon,shot_status,photo_url,notes
,359023372,,,,,,,,,filmed,./media/CentralBaptistChurch.JPG,Exterior filmed July 2026
,1028763911,,,,,,,,,filmed,./media/SaintMarySprings.JPG,Exterior filmed July 2026
,,1609938,,,,,,,,filmed,./media/FirstPresChurchHS.JPG,Exterior filmed July 2026
```

`shot_status` values: `pending` (default), `filmed`, `skipped`. The popup shows the photo; the sidebar and stats panel reflect filmed count.

**Confidence:** `filmed` churches are always `high` (field-verified) and gain a `field` source in the popup. Others use source count: 1 = low, 2 = medium, 3+ = high.

## Rebuild the dashboard

```bash
cd scripts
python3 normalize_churches.py
```

Then reload `index.html`.

## Fieldwork driving checklist (all locations)

Export a complete checklist grouped into geographic driving routes:

```bash
cd scripts
python3 export_fieldwork_checklist.py
```

This writes `data/fieldwork_checklist.csv` with all churches, suggested route groups (~12 stops each), stop order within each route, Google Maps links, and empty `visited` / `notes` columns for checkoffs.

Open the CSV in Excel, Numbers, or Google Sheets. Filter by the `route` column to plan one driving day at a time. Re-run after `normalize_churches.py` if the church list changes.

Already-filmed churches are marked in the `filmed` column so you can skip or filter them out.

## Arkansas Secretary of State (optional)

1. Export Hot Springs nonprofit corporations from [Arkansas SOS BCS](https://www.sos.arkansas.gov/business-commercial-services-bcs/)
2. Save as `data/raw/sos_nonprofits_export.csv`
3. Run `python3 fetch_sos_churches.py`
4. Geocode SOS addresses (or add `lat`/`lon` manually in enrichment)
5. Re-run `normalize_churches.py`

SOS tells you **who incorporated**, not necessarily where worship happens today.
