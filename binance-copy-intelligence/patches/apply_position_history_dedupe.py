from pathlib import Path

# Runtime idempotency guard for duplicate trade-history rows. Keep the database's
# unique constraint; discard duplicate new Position objects before INSERT so a
# repeated page/API record cannot roll back an entire Spot history batch.
p = Path("/app/app.py")
s = p.read_text()
marker = "POSITION_EXTERNAL_KEY_DEDUPE_V1"
if marker not in s:
    s += r'''

# POSITION_EXTERNAL_KEY_DEDUPE_V1
# History endpoints can repeat rows across pages or successive polls. The
# (trader_id, external_key) unique constraint remains authoritative; this hook
# avoids a repeated incoming row aborting the entire batch transaction.
try:
    from sqlalchemy import event as _dedupe_event, select as _dedupe_select
    from sqlalchemy.orm import Session as _SASession
    from models import Position as _DedupePosition

    def _dedupe_position_rows_before_flush(session, flush_context, instances):
        pending = [
            obj for obj in list(session.new)
            if isinstance(obj, _DedupePosition)
            and getattr(obj, "trader_id", None) is not None
            and getattr(obj, "external_key", None) not in (None, "")
        ]
        if not pending:
            return
        # Deduplicate within the incoming flush first, preserving the first row.
        seen_pending = set()
        duplicate_objects = []
        for obj in pending:
            key = (obj.trader_id, str(obj.external_key))
            if key in seen_pending:
                duplicate_objects.append(obj)
            else:
                seen_pending.add(key)
        for obj in duplicate_objects:
            session.expunge(obj)

        # Also remove incoming rows whose stable external identity already exists.
        by_trader = {}
        for obj in pending:
            if obj in duplicate_objects:
                continue
            by_trader.setdefault(obj.trader_id, set()).add(str(obj.external_key))
        existing = set()
        for trader_id, external_keys in by_trader.items():
            if not external_keys:
                continue
            rows = session.execute(
                _dedupe_select(_DedupePosition.external_key).where(
                    _DedupePosition.trader_id == trader_id,
                    _DedupePosition.external_key.in_(list(external_keys))
                )
            ).all()
            existing.update((trader_id, str(row[0])) for row in rows)
        for obj in pending:
            if obj not in duplicate_objects and (obj.trader_id, str(obj.external_key)) in existing:
                session.expunge(obj)

    if not getattr(_SASession, "_position_external_key_dedupe_installed", False):
        _dedupe_event.listen(_SASession, "before_flush", _dedupe_position_rows_before_flush)
        _SASession._position_external_key_dedupe_installed = True
except Exception:
    app.logger.exception("position_external_key_dedupe_install_failed")
'''
    p.write_text(s)
print("Position-history dedupe guard installed")
