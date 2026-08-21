import duckdb, time
t0=time.time()
c=duckdb.connect(); c.execute("INSTALL httpfs; LOAD httpfs;")
U="https://www2.census.gov/ces/gridded_eif/gridded_eif_pop_ageracesex_2022.parquet"

c.execute(f"""CREATE VIEW agg AS
SELECT x.county_fips, x.state_fips, d.age_group, d.race_ethnicity, d.sex,
       sum(d.n_noise) n_raw, sum(d.n_noise_postprocessed) n_pp, count(*) n_cells
FROM read_parquet('{U}') d
JOIN read_parquet('xwalk_county_2024.parquet') x
  ON d.grid_lon=x.grid_lon AND d.grid_lat=x.grid_lat
WHERE x.county_fips IS NOT NULL
GROUP BY 1,2,3,4,5""")

c.execute("CREATE TABLE county AS SELECT * FROM agg")
print(f"county rows: {c.execute('SELECT count(*) FROM county').fetchone()[0]:,}")
print(f"counties    : {c.execute('SELECT count(DISTINCT county_fips) FROM county').fetchone()[0]:,}")
print(f"[{time.time()-t0:.0f}s]\n")

print("RECONCILIATION vs verified national totals (§2.3):")
exp={'White':(181814741,181814692),'Hispanic':(50773661,50773676),'Black':(38020972,38020986),
     'Other/Unknown':(33192479,33192532),'Asian':(13380040,13380031),'AIAN':(2749175,2749162)}
got=dict((r[0],(r[1],r[2])) for r in c.execute(
  "SELECT race_ethnicity, round(sum(n_raw)), round(sum(n_pp)) FROM county GROUP BY 1").fetchall())
print(f"{'race':<15}{'expected raw':>15}{'county-agg raw':>16}{'diff':>9}")
tr=tp=0
for k,(er,ep) in exp.items():
    gr,gp=got[k]; tr+=gr; tp+=gp
    print(f"{k:<15}{er:>15,}{int(gr):>16,}{int(gr)-er:>9,}")
print(f"\n{'TOTAL raw':<15}{sum(v[0] for v in exp.values()):>15,}{int(tr):>16,}{int(tr)-sum(v[0] for v in exp.values()):>9,}")
c.execute("COPY county TO 'county_ageracesex_2022.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)")
import os; print(f"\nwrote county_ageracesex_2022.parquet ({os.path.getsize('county_ageracesex_2022.parquet')/1e6:.1f} MB)")
