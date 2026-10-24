"""Regression tests for immediate paper-cycle requests and daily retry cooldown."""
import os, tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta

_tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False); _tmp.close()
os.environ['DATABASE_URL'] = 'sqlite:///' + _tmp.name
os.environ['SECRET_KEY'] = 'paper-scheduler-regression-not-for-production'
os.environ['ADMIN_PASSWORD'] = 'paper-scheduler-test-password'
from app.worker import paper_cycle_due, PAPER_ENGINE_VERSION


def run():
    now = datetime(2026, 10, 18, 15, 0, tzinfo=timezone.utc)
    today_cycle = (now - timedelta(hours=2)).isoformat()
    # A Start click always schedules an immediate cycle, even if there was one today.
    due, req = paper_cycle_due({'paper_last_cycle':today_cycle,'paper_cycle_requested_at':now.isoformat()},
        {'paper_request_handled_at':None,'paper_cycle_attempted_at':today_cycle}, now)
    assert due and req == now.isoformat(), (due, req)
    # When a same-day request was already handled and the universe is unchanged,
    # no needless duplicate cycle fires.
    same_runtime={'paper_request_handled_at':now.isoformat(),'paper_cycle_attempted_at':today_cycle,
                  'scan_universe_count':14,'last_strategy_cycle':{'scan_universe_count':14,'paper_engine_version':PAPER_ENGINE_VERSION}}
    due, req = paper_cycle_due({'paper_last_cycle':today_cycle,'paper_cycle_requested_at':now.isoformat()},
        same_runtime, now)
    assert not due and req is None, (due, req)
    # If the scan expands beyond the universe used by today's older rebalance,
    # run one paper-only cycle immediately instead of waiting until tomorrow.
    expanded_cfg={'paper_last_cycle':today_cycle}
    expanded_runtime={'paper_cycle_attempted_at':today_cycle,'scan_universe_count':60,
                      'last_strategy_cycle':{'scan_universe_count':14,'paper_engine_version':PAPER_ENGINE_VERSION}}
    due, req=paper_cycle_due(expanded_cfg,expanded_runtime,now)
    assert due and req is None, (due,req)
    # Once a cycle has run against the new universe, no second same-day rebalance fires.
    expanded_runtime['last_strategy_cycle']={'scan_universe_count':60,'paper_engine_version':PAPER_ENGINE_VERSION}
    due, req=paper_cycle_due(expanded_cfg,expanded_runtime,now)
    assert not due and req is None, (due,req)
    # A new engine rule version triggers one immediate paper-only cycle even when
    # the ordinary 15-minute retry cooldown has not elapsed.
    changed_runtime={'scan_universe_count':60,'paper_cycle_attempted_at':(now-timedelta(minutes=2)).isoformat(),
                     'last_strategy_cycle':{'scan_universe_count':60,'paper_engine_version':'old-version'}}
    due, req=paper_cycle_due({'paper_last_cycle':today_cycle},changed_runtime,now)
    assert due and req is None, (due,req)
    changed_runtime['paper_engine_migration_attempted_version']=PAPER_ENGINE_VERSION
    due, req=paper_cycle_due({'paper_last_cycle':today_cycle},changed_runtime,now)
    assert not due and req is None, (due,req)
    # If no cycle ran today, a stale attempt is retried after cooldown.
    yesterday=(now-timedelta(days=1)).isoformat()
    stale_attempt=(now-timedelta(minutes=20)).isoformat()
    due, _ = paper_cycle_due({'paper_last_cycle':yesterday}, {'paper_cycle_attempted_at':stale_attempt}, now)
    assert due
    # But a recent failed attempt is backed off, preventing one-minute API hammering.
    recent_attempt=(now-timedelta(minutes=2)).isoformat()
    due, _ = paper_cycle_due({'paper_last_cycle':yesterday}, {'paper_cycle_attempted_at':recent_attempt}, now)
    assert not due
    print('PAPER SCHEDULER REGRESSION PASSED: immediate start overrides daily guard; handled requests deduplicate; retries back off.')

if __name__ == '__main__':
    try: run()
    finally:
        try: Path(_tmp.name).unlink()
        except OSError: pass
