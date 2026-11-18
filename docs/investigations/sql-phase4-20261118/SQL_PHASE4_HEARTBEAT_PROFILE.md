# SQL Phase 4 Heartbeat Profile

Synthetic profile (`sql_read_sharing_profile_20261117.py`, 10 iterations):

| Scale | Heartbeat API SQL / connections / rows / p50 wall |
| --- | --- |
| 50 trains / 100 MR / 200 IP | 30 / 6 / 102 / 19.06 ms |
| 100 trains / 200 MR / 400 IP | 30 / 6 / 202 / 23.39 ms |
| 200 trains / 400 MR / 800 IP | 34 / 7 / 803 / 44.10 ms |

SQL remains approximately constant while inventory rows grow. Heartbeat target/syslog cold-read cases have no per-MR query growth. Persistence already uses bounded batches (256) and the supervisor keeps revision/site consistency under its lifecycle locks.

No cache was introduced: an indefinite cache would risk stale dynamic inventory, freshness and site isolation. No Heartbeat production code was changed in Phase 4.

Validation: Heartbeat state, resident lifecycle, inventory and Ground API tests passed in the 145-test consumer suite.

Final gate refresh: PR #122 HEAD `8c1aed0184` retains the same bounded read design. No Heartbeat production code was added after this profile.
