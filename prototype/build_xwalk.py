import duckdb, geopandas as gpd, pandas as pd, time
t0=time.time()
c=duckdb.connect(); c.execute("INSTALL httpfs; LOAD httpfs;")
U="https://www2.census.gov/ces/gridded_eif/gridded_eif_pop_ageracesex_2022.parquet"

print("1. pulling distinct cells...", flush=True)
cells = c.execute(f"""SELECT DISTINCT grid_lon, grid_lat FROM read_parquet('{U}')""").df()
print(f"   {len(cells):,} cells  [{time.time()-t0:.0f}s]", flush=True)

print("2. reading counties...", flush=True)
cty = gpd.read_file("counties/tl_2024_us_county.shp")[["GEOID","NAME","STATEFP","geometry"]]
print(f"   {len(cty):,} counties, CRS={cty.crs.to_string()}", flush=True)

print("3. building points (EPSG:4326)...", flush=True)
pts = gpd.GeoDataFrame(cells,
    geometry=gpd.points_from_xy(cells.grid_lon.astype(float), cells.grid_lat.astype(float)),
    crs="EPSG:4326").to_crs(cty.crs)

print("4. spatial join...", flush=True)
j = gpd.sjoin(pts, cty, how="left", predicate="within")
j = j[~j.index.duplicated(keep="first")]     # cells on a shared border
print(f"   joined [{time.time()-t0:.0f}s]", flush=True)

matched = j.GEOID.notna().sum()
print(f"\n   matched : {matched:,} ({100*matched/len(j):.2f}%)")
print(f"   unmatched: {len(j)-matched:,}")

out = j[["grid_lon","grid_lat","GEOID","STATEFP"]].rename(
    columns={"GEOID":"county_fips","STATEFP":"state_fips"})
out.to_parquet("xwalk_county_2024.parquet", index=False)
print(f"\n   wrote xwalk_county_2024.parquet  [{time.time()-t0:.0f}s]")
