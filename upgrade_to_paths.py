"""Explicit, backed-up strategy migration. Run only after stopping the paused service."""
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
import time

from candle_paths import VERSION, PAPER_CONFIG


def migrate(directory):
    controls = json.loads((directory/'controls.json').read_text(encoding='utf-8'))
    if not controls['paused'] or controls['flatten']:
        raise ValueError('Pause and fully close the old paper position before migration')
    # Same account, same money: no reset or erased losses.
    db = sqlite3.connect(directory/'paper.sqlite3')
    try:
        s = json.loads(db.execute('SELECT body FROM state WHERE id=1').fetchone()[0])
        if s['identity']['version'] == VERSION:
            print('Account already uses Candle Paths; balance retained.')
            return
        if s['identity']['version'] != 'eth-guard-v3.0' or s['position'] is not None:
            raise ValueError('Unexpected strategy or open position; refusing migration')
        backup = directory/f'paper-before-v4-{int(time.time())}.sqlite3'
        with sqlite3.connect(backup) as target:
            db.backup(target)
        db.execute('BEGIN IMMEDIATE')
        old_version = s['identity']['version']
        s['identity']['version'] = VERSION
        s['identity']['config'] = asdict(PAPER_CONFIG)
        db.execute('UPDATE state SET body=? WHERE id=1',(json.dumps(s),))
        db.execute('INSERT INTO events(kind,body) VALUES (?,?)',('MIGRATION',json.dumps(dict(time=time.time(),
                   reason=f'{old_version} -> {VERSION}; balance, trades and risk halts retained',cash=s['cash']))))
        db.commit()
        print(f'Migrated to {VERSION}; retained cash ${s["cash"]:.6f}; backup {backup.name}')
    finally:
        db.close()


if __name__ == '__main__':
    from guard_server import SessionLock
    directory = Path(__file__).with_name('guard_live')
    lease = SessionLock(directory/'session.lock')
    try:
        migrate(directory)
    finally:
        lease.close()
