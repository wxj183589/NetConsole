# SQL Phase 4 Mesh Profile

Synthetic profile (`sql_phase3_profile_20261118.py`, 30 iterations) against isolated fixtures:

| Scale | Baseline SQL / connections / p50 wall | Phase 3 optimized SQL / connections / p50 wall |
| --- | --- | --- |
| 50 MR / 100 links | 884 / 197 / 437.13 ms | 27 / 6 / 14.30 ms |
| 100 MR / 200 links | 1,784 / 397 / 897.91 ms | 27 / 6 / 22.36 ms |
| 200 MR / 400 links | 3,584 / 797 / 2,295.90 ms | 27 / 6 / 48.13 ms |

The current public Mesh path already removes the primary peer identity N+1. The detail path was inspected for a further safe change, but its separate history/current/event reads are bounded request components and changing them would duplicate existing Phase 3 preload logic without a demonstrated contract benefit. No Mesh production code was changed in Phase 4.

Validation: `tests/test_ac_mesh_link_query_service.py` passed as part of the 145-test consumer suite. Site isolation, freshness, exact identity matching and pagination remain covered.

Final gate refresh: PR #122 HEAD `8c1aed0184` was reviewed by Codex with no major findings. No Mesh production code was added after this profile.
