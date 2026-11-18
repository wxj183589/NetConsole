# Syslog Optimization Proposal

No product code is changed in this audit.

## P0: serialize/coalesce projection retries

Evidence: 161 `ValueError: ground unattended raw file not found` failures and 161 rollbacks in one phase-separated 400 MR run; five repeats had 811 rollbacks total. The likely ordering bug is deferred raw-file registration racing the projection checkpoint. Expected benefit is removal of repeated projection work. Preserve raw-first durability and replay.

## P1: field-aware no-op projection guards

Position and boot projections run for every verified event. Guard only fields whose business semantics permit it; retain timestamps, freshness and counters. Benefit is not yet quantified.

## P1: batch verified boot/identity projection

`touch_boot_syslog` opens a separate transaction per event. Coalesce it with the existing event transaction only after proving boot activation ordering and identity durability.

Do not deduplicate raw evidence, discard overflow, use `busy_timeout` as the only fix, or introduce schema/index changes in this audit.
