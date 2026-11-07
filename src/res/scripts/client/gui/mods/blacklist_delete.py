# -*- coding: utf-8 -*-
"""黑名单批量删除（按名单）+ 删除报告。

由 mod_blacklist_exporter 调用：车库出现 marker 文件后开始删。

删除接口与游戏里右键"从黑名单移除"完全一致：
    proto_getter(PROTO_TYPE.XMPP).contacts.removeIgnored(dbID)
"""

from __future__ import absolute_import

import json
import os
import time
import traceback

import BigWorld
from debug_utils import LOG_NOTE, LOG_CURRENT_EXCEPTION

LOG_PREFIX = '[BLX-DEL]'


def _log(msg):
    try:
        LOG_NOTE(LOG_PREFIX, msg)
    except Exception:
        pass


def _ts(sec):
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(sec))


def _all_paths():
    paths = []
    appdata = os.environ.get('APPDATA')
    if appdata:
        paths.append(os.path.join(appdata, 'Wargaming.net', 'WorldOfTanks'))
    try:
        paths.append(os.getcwd())
    except Exception:
        pass
    return [p for p in paths if p and os.path.isdir(p)]


def _find_file(name):
    for base in _all_paths():
        path = os.path.join(base, name)
        if os.path.isfile(path):
            return path
    return None


def _write_all(name, text):
    data = text.encode('utf-8') if isinstance(text, unicode) else text
    for base in _all_paths():
        try:
            with open(os.path.join(base, name), 'wb') as fh:
                fh.write(data)
        except Exception:
            pass


def _get_proto():
    from messenger.proto import proto_getter
    from messenger.m_constants import PROTO_TYPE

    class _Holder(object):
        @proto_getter(PROTO_TYPE.XMPP)
        @property
        def proto(self):
            return None

    return _Holder().proto


def _get_users_storage():
    from messenger.storage import descriptor as storage_descriptor
    from messenger.storage import UsersStorage
    return (getattr(storage_descriptor, '_STORAGE', None) or {}).get(UsersStorage)


def _still_ignored(storage, db_id):
    if storage is None:
        return None
    try:
        user = storage.getUser(int(db_id))
        if user is None:
            return False
        return 'ignored' in set(user.getTags())
    except Exception:
        return None


def _write_report(rows, state, done, phase):
    now = time.time()
    payload = {
        'version': 1,
        'phase': phase,
        'started_at': state['started_str'],
        'finished_at': _ts(now) if phase == 'done' else '',
        'duration_sec': int(now - state['started']) if phase == 'done' else int(now - state['started']),
        'total': len(rows),
        'ok': sum(1 for r in rows if r['result'] == 'ok'),
        'failed': sum(1 for r in rows if r['result'] != 'ok'),
        'processed': done,
        'rows': rows,
    }
    _write_all('blacklist_delete_report.json',
               json.dumps(payload, ensure_ascii=False, indent=1))

    lines = ['用户ID,昵称,账号创建时间,最后战斗时间,距今天数,总场次,网页有效,结果,耗时(秒),执行操作时间']
    for r in rows:
        lines.append(','.join([
            str(r.get('account_id') or ''),
            '"%s"' % (r.get('nickname') or '').replace('"', '""'),
            r.get('created_str') or '',
            r.get('last_battle_str') or '',
            str(r.get('days') if r.get('days') is not None else ''),
            str(r.get('battles') if r.get('battles') else ''),
            '是' if r.get('web_valid') else '否',
            r.get('result') or '',
            '%.1f' % (r.get('elapsed') or 0),
            r.get('deleted_at') or '',
        ]))
    _write_all('blacklist_delete_report.csv', '\n'.join(lines))
    return payload


def maybe_delete(players, config):
    """检查 marker -> 执行删除 -> 写报告。players 只用于兜底（没名单时）。"""
    marker = config.get('delete_marker', 'blacklist_delete_go.txt')
    list_name = config.get('delete_list', 'blacklist_delete_list.json')

    marker_path = _find_file(marker)
    if marker_path is None:
        return
    _log('marker found: %s' % marker_path)

    targets = []
    list_path = _find_file(list_name)
    if list_path:
        try:
            payload = json.loads(open(list_path, 'rb').read().decode('utf-8-sig'))
            targets = payload.get('players') or []
            _log('targets from %s: %d' % (list_path, len(targets)))
        except Exception:
            _log('read list failed:\n%s' % traceback.format_exc())

    if not targets:
        targets = [{'account_id': p.get('account_id'), 'nickname': p.get('nickname'),
                    'created_at': p.get('created_at') or p.get('reg_timestamp'),
                    'last_battle_time': p.get('last_battle_time'), 'battles': p.get('battles')}
                   for p in players if p.get('account_id')]
        _log('fallback targets: %d' % len(targets))

    try:
        os.remove(marker_path)
    except Exception:
        _log('remove marker failed: %s' % traceback.format_exc())

    _log('delete scheduled in %.0fs, %d targets'
         % (config.get('delete_confirm_delay', 10.0), len(targets)))
    BigWorld.callback(config.get('delete_confirm_delay', 10.0),
                      lambda: _begin(targets, config))


def _begin(targets, config):
    try:
        proto = _get_proto()
        storage = _get_users_storage()
        if proto is None:
            _log('proto not found, abort')
            return
        if storage is None:
            _log('users storage not found, abort')
            return
    except Exception:
        _log('init failed:\n%s' % traceback.format_exc())
        LOG_CURRENT_EXCEPTION()
        return

    state = {'started': time.time(), 'started_str': _ts(time.time())}
    rows = []
    for t in targets:
        rows.append({
            'account_id': t.get('account_id'),
            'nickname': t.get('nickname') or '',
            'created_at': t.get('created_at') or 0,
            'created_str': _ts(t['created_at']) if t.get('created_at') else '',
            'last_battle_time': t.get('last_battle_time') or 0,
            'last_battle_str': _ts(t['last_battle_time']) if t.get('last_battle_time') else '',
            'days': t.get('days'),
            'battles': t.get('battles') or 0,
            'web_valid': bool(t.get('web_valid')),
            'result': 'pending',
            'elapsed': 0,
            'deleted_at': '',
        })

    queue = list(rows)
    interval = float(config.get('delete_interval', 0.9))
    _log('delete start: %d targets, interval %.2fs' % (len(queue), interval))
    _write_report(rows, state, 0, 'running')

    def _step():
        if not queue:
            payload = _write_report(rows, state, len(rows), 'done')
            _log('delete finished: ok=%d failed=%d duration=%ds'
                 % (payload['ok'], payload['failed'], payload['duration_sec']))
            return

        row = queue.pop(0)
        started = time.time()
        try:
            proto.contacts.removeIgnored(int(row['account_id']), False)
        except Exception:
            _log('removeIgnored failed for %s:\n%s'
                 % (row['account_id'], traceback.format_exc()))
            row['result'] = 'exception'
            row['elapsed'] = time.time() - started
            BigWorld.callback(interval, _step)
            return

        def _verify():
            ignored = _still_ignored(storage, row['account_id'])
            if ignored is False:
                row['result'] = 'ok'
            elif ignored is True:
                row['result'] = 'still_ignored'
            else:
                row['result'] = 'unverified'
            row['elapsed'] = time.time() - started
            row['deleted_at'] = _ts(time.time())
            if len([r for r in rows if r['result'] != 'pending']) % 10 == 0:
                _write_report(rows, state, len([r for r in rows if r['result'] != 'pending']), 'running')
            BigWorld.callback(interval, _step)

        BigWorld.callback(1.0, _verify)

    BigWorld.callback(0.5, _step)
