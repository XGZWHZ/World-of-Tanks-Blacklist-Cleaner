# -*- coding: utf-8 -*-
"""
Blacklist Exporter —— 坦克世界黑名单导出 MOD

进车库后自动：
  1. 从客户端联系人存储里找出所有"被拉黑"的玩家（USER_TAG.IGNORED）；
  2. 立刻把名单写成 JSON（先保证有产物）；
  3. 再逐个向客户端请求玩家档案（dossier），取 lastBattleTime（最后战斗时间）；
  4. 边查边回写 JSON，进度也在里面。

产物（两个位置都写，哪个成功算哪个）：
  %APPDATA%\\Wargaming.net\\WorldOfTanks\\blacklist_export.json
  <游戏根目录>\\blacklist_export.json
诊断日志（API 探测结果）：
  %APPDATA%\\Wargaming.net\\WorldOfTanks\\blacklist_diag.txt
  python.log 里搜 [BLX]

兼容：WoT 客户端 2.x（Python 2.7）。所有入口都包了 try/except，失败只会写日志，不会崩游戏。
"""

from __future__ import absolute_import

import json
import os
import sys
import time
import traceback

from debug_utils import LOG_CURRENT_EXCEPTION, LOG_NOTE

VERSION = '2.0.2'
LOG_PREFIX = '[BLX]'

CONFIG = {
    # 进车库后多久开始（秒）。给联系人同步留时间，别改太小。
    'start_delay': 20.0,
    # 是否查询最后战斗时间（关掉就只导出名单）
    'fetch_last_battle': True,
    # 每次进游戏最多查多少人（1000 人全查约 6 分钟，可调大）
    'max_fetch': 1000,
    # 两次查询之间的间隔（秒），太小学生会被服务器限速
    'fetch_interval': 0.2,
    'fetch_timeout': 12.0,
    # 每查多少个回写一次文件
    'flush_every': 15,
    'file_name': 'blacklist_export.json',
     'diag_name': 'blacklist_diag.txt',
    # ---- 删除模式 ----
    'delete_mode': True,
    'delete_list': 'blacklist_delete_list.json',
    'delete_marker': 'blacklist_delete_go.txt',
    'delete_confirm_delay': 10.0,
    'delete_interval': 0.9,
}

_ran = False
_attempts = 0
_diag = []


# ------------------------------------------------------------------ 基础工具

def _log(msg):
    try:
        LOG_NOTE(LOG_PREFIX, msg)
    except Exception:
        pass
    _diag.append(str(msg))


def _diag_log(msg):
    _diag.append(str(msg))


def _paths():
    paths = []
    appdata = os.environ.get('APPDATA')
    if appdata:
        paths.append(os.path.join(appdata, 'Wargaming.net', 'WorldOfTanks'))
    try:
        paths.append(os.getcwd())
    except Exception:
        pass
    return paths


def _write_text(name, text):
    """往所有候选目录写同一个文件，返回成功的路径列表。"""
    ok = []
    data = text.encode('utf-8') if isinstance(text, unicode) else text
    for base in _paths():
        try:
            path = os.path.join(base, name)
            fh = open(path, 'wb')
            try:
                fh.write(data)
            finally:
                fh.close()
            ok.append(path)
        except Exception:
            _diag_log('write failed: %r' % (base,))
    return ok


def _dump_json(payload):
    return json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True)


# ------------------------------------------------------------------ API 探测

def _describe(obj, limit=40):
    try:
        attrs = [a for a in dir(obj) if not a.startswith('_')]
    except Exception:
        attrs = ['<dir failed>']
    return '%s attrs=%s' % (type(obj), ','.join(attrs[:limit]))


def _storage_users(storage):
    """从 StorageDecorator 里取出 users 存储。

    2.4.x 的 StorageDecorator 只暴露 clear/init/restoreFromCache/switch，
    真正实例在 messenger.storage.descriptor._STORAGE 这个模块级字典里
    （key 是存储类，value 是单例）。
    """
    # 1) 2.4.x 注册表（最可靠）
    try:
        from messenger.storage import descriptor as storage_descriptor
        from messenger.storage import UsersStorage
        store = getattr(storage_descriptor, '_STORAGE', None) or {}
        users = store.get(UsersStorage)
        if users is not None:
            _diag_log('users storage: descriptor._STORAGE[UsersStorage]')
            return users
        for value in store.values():
            if value is not None and hasattr(value, 'getList'):
                _diag_log('users storage: descriptor._STORAGE[*] %r' % (type(value),))
                return value
    except Exception:
        _diag_log('descriptor._STORAGE probe failed:\n%s' % traceback.format_exc())

    if storage is None:
        return None

    # 2) 旧的属性/方法式暴露
    users = getattr(storage, 'users', None)
    if users is not None:
        return users

    accessor = getattr(storage, 'storage', None)
    if callable(accessor):
        try:
            from messenger.storage import UsersStorage
            keys = ('users', UsersStorage)
        except Exception:
            keys = ('users',)
        for key in keys:
            try:
                users = accessor(key)
                if users is not None:
                    return users
            except Exception:
                pass

    getter = getattr(storage, 'getStorage', None)
    if callable(getter):
        for key in ('users', 'UsersStorage'):
            try:
                users = getter(key)
                if users is not None:
                    return users
            except Exception:
                pass

    return None


def _find_messenger_entry():
    """找到持有 users 存储的信使单例。客户端各版本命名不同，这里逐个试。"""
    tried = []

    def _check(obj, label):
        tried.append(label)
        try:
            if obj is None or isinstance(obj, type):
                return None
            storage = getattr(obj, 'storage', None)
            if storage is None:
                return None
            if _storage_users(storage) is None:
                return None
        except Exception:
            return None
        _diag_log('messenger entry: %s' % label)
        return obj

    # 1) 2.x 的正式入口：messenger.MessengerEntry.g_instance
    try:
        import messenger.MessengerEntry as entry_mod
        for name in ('g_instance', 'g_messenger', 'messenger', 'entry'):
            try:
                obj = _check(getattr(entry_mod, name, None), 'MessengerEntry.%s' % name)
            except Exception:
                obj = None
            if obj is not None:
                return obj

        inst = getattr(entry_mod, 'g_instance', None)
        _diag_log('g_instance = %r' % (inst,))
        if inst is not None:
            try:
                _diag_log('g_instance dict: %s' % ','.join(sorted(inst.__dict__.keys()))[:300])
            except Exception:
                pass
            st = getattr(inst, 'storage', None)
            _diag_log('g_instance.storage = %r' % (st,))
            _diag_log(_describe(st))
            _diag_log('storage.users probe: %r' % (_storage_users(st),))
    except Exception:
        _diag_log('import messenger.MessengerEntry failed:\n%s' % traceback.format_exc())

    # 2) 扫所有已加载的 messenger* 模块里的全局对象
    for mod_name in sorted(sys.modules.keys()):
        if not mod_name.startswith('messenger'):
            continue
        mod = sys.modules.get(mod_name)
        if mod is None:
            continue
        for attr in dir(mod):
            if attr.startswith('__'):
                continue
            try:
                obj = getattr(mod, attr)
            except Exception:
                continue
            found = _check(obj, '%s.%s' % (mod_name, attr))
            if found is not None:
                return found

    _diag_log('messenger entry NOT FOUND, tried: %s' % ', '.join(tried[-15:]))
    return None


def _get_users(entry):
    storage = entry.storage
    users_storage = _storage_users(storage)
    if users_storage is None:
        _diag_log('storage %r attrs: %s' % (
            type(storage), ', '.join(a for a in dir(storage) if not a.startswith('_'))[:500]))
        raise RuntimeError('users storage not found on %r' % (type(storage),))

    # 2.4.x 的 getList(criteria) 需要 criteria 对象，直接读内部字典更省事
    contacts = getattr(users_storage, '_UsersStorage__contacts', None)
    if contacts is not None:
        try:
            users = list(contacts.values())
            _diag_log('users from __contacts: %d' % len(users))
            return users
        except Exception:
            _diag_log('__contacts read failed:\n%s' % traceback.format_exc())

    try:
        return list(users_storage.getList())
    except TypeError:
        _diag_log('getList needs criteria, no fallback available')
        raise


def _user_tags(user):
    for getter in ('getTags', 'tags'):
        try:
            value = getattr(user, getter)
            value = value() if callable(value) else value
            if value:
                return set(value)
        except Exception:
            pass
    return set()


def _user_id(user):
    for getter in ('getID', 'dbID', 'id'):
        try:
            value = getattr(user, getter)
            value = value() if callable(value) else value
            if value:
                return int(value)
        except Exception:
            pass
    return None


def _user_name(user):
    for getter in ('getName', 'name'):
        try:
            value = getattr(user, getter)
            value = value() if callable(value) else value
            if value:
                return value
        except Exception:
            pass
    return ''


def _ignored_only(users):
    try:
        from messenger.m_constants import USER_TAG
        ignored_tags = {USER_TAG.IGNORED, USER_TAG.IGNORED_TMP}
    except Exception:
        _diag_log('USER_TAG import failed:\n%s' % traceback.format_exc())
        ignored_tags = {'ignored', 'tmp_ignored'}

    result = []
    for user in users:
        tags = _user_tags(user)
        if tags & ignored_tags:
            result.append((user, tags))
    return result


def _entity_info(user, tags):
    info = {
        'account_id': _user_id(user),
        'nickname': _user_name(user),
        'tags': sorted(tags),
    }
    try:
        info['online'] = bool(user.isOnline())
    except Exception:
        info['online'] = None
    try:
        clan = user.getClanInfo() or {}
        if isinstance(clan, dict):
            info['clan'] = clan.get('clanAbbrev') or clan.get('abbrev') or ''
    except Exception:
        pass
    info['last_battle_time'] = 0
    info['battles'] = 0
    return info


# ------------------------------------------------------------------ 最后战斗时间

def _find_dossier_requester():
    """2.4.x：缓存对象由依赖注入管理，走 dependency.instance(IItemsCache)。"""

    # 1) 正规入口
    try:
        from helpers import dependency
        from skeletons.gui.shared import IItemsCache
        cache = dependency.instance(IItemsCache)
        if cache is None:
            _diag_log('dependency.instance(IItemsCache) -> None')
        else:
            items = getattr(cache, 'items', None)
            dossiers = getattr(items, 'dossiers', None) if items is not None else None
            if dossiers is not None:
                _diag_log('dossier requester: dependency.instance(IItemsCache).items.dossiers')
                return dossiers
            _diag_log('IItemsCache=%r items=%r dossiers=%r' % (cache, items, dossiers))
    except Exception:
        _diag_log('dependency.instance(IItemsCache) failed:\n%s' % traceback.format_exc())

    # 2) 老式模块级全局
    import gui.shared as gui_shared

    candidates = []
    for attr in ('cache', 'g_itemsCache', 'itemsCache', 'items_cache'):
        obj = getattr(gui_shared, attr, None)
        if obj is not None:
            candidates.append(('gui.shared.%s' % attr, obj))

    for label, cache in candidates:
        try:
            items = getattr(cache, 'items', None)
            if items is None:
                continue
            dossiers = getattr(items, 'dossiers', None)
            if dossiers is not None:
                _diag_log('dossier requester: %s.items.dossiers -> %r' % (label, dossiers))
                return dossiers
        except Exception:
            _diag_log('dossier probe failed at %s:\n%s' % (label, traceback.format_exc()))

    # 3) 兜底：在 gui.shared 里找任何带 items.dossiers 的对象
    for name in dir(gui_shared):
        if name.startswith('_'):
            continue
        try:
            obj = getattr(gui_shared, name)
            items = getattr(obj, 'items', None)
            dossiers = getattr(items, 'dossiers', None) if items is not None else None
            if dossiers is not None:
                _diag_log('dossier requester: gui.shared.%s.items.dossiers' % name)
                return dossiers
        except Exception:
            continue

    _diag_log('dossier requester NOT FOUND')
    return None


def _extract_last_battle(dossier):
    """从 UserDossier 里抠 lastBattleTime，顺序尝试多种结构。"""
    if dossier is None:
        return None

    for name in ('getLastBattleTime',):
        fn = getattr(dossier, name, None)
        if callable(fn):
            try:
                value = fn()
                if value:
                    return int(value)
            except Exception:
                pass

    # 有些版本回调给的是“档案包装对象”，真正的统计在 .getStats()/.stats 里
    for getter in ('getStats', 'stats', 'getStatistic'):
        try:
            holder = getattr(dossier, getter)
            holder = holder() if callable(holder) else holder
            fn = getattr(holder, 'getLastBattleTime', None)
            if callable(fn):
                value = fn()
                if value:
                    return int(value)
        except Exception:
            pass

    for holder_name in ('account', 'accountDossier', 'account_dossier'):
        holder = getattr(dossier, holder_name, None)
        if holder is None:
            continue
        fn = getattr(holder, 'getLastBattleTime', None)
        if callable(fn):
            try:
                value = fn()
                if value:
                    return int(value)
            except Exception:
                pass
        if isinstance(holder, dict):
            for key in ('lastBattleTime', 'last_battle_time', 'lastBattle'):
                if holder.get(key):
                    try:
                        return int(holder[key])
                    except Exception:
                        pass

    if isinstance(dossier, dict):
        for key in ('lastBattleTime', 'last_battle_time'):
            if dossier.get(key):
                try:
                    return int(dossier[key])
                except Exception:
                    pass

    # 实在没有，就把属性名记进诊断，方便下一版修
    try:
        _diag_log('dossier attrs: %s' % ', '.join(
            sorted(str(a) for a in dir(dossier) if not str(a).startswith('_'))[:40]))
    except Exception:
        pass
    return None


def _parse_dossier(dossier):
    """dossier 串 -> (lastBattleTime, battles)。

    客户端自己的写法：descr['total']['lastBattleTime']
    """
    if not dossier:
        return None, None, None
    try:
        import dossiers2
        descr = dossiers2.getAccountDossierDescr(dossier)
    except Exception:
        _diag_log('getAccountDossierDescr failed:\n%s' % traceback.format_exc())
        return None, None, None

    blocks = []
    for name in ('total', 'a15x15'):
        try:
            blocks.append((name, descr[name]))
        except Exception:
            pass

    for name, block in blocks:
        value = _block_get(block, 'lastBattleTime')
        if value is not None:
            return int(value), _block_get(block, 'battles'), _block_get(block, 'creationTime')

    # 兜底：遍历所有 block
    try:
        for name in ('total', 'a15x15', 'a30x30', 'clan', 'company'):
            try:
                block = descr[name]
            except Exception:
                continue
            value = _block_get(block, 'lastBattleTime')
            if value is not None:
                return int(value), _block_get(block, 'battles'), _block_get(block, 'creationTime')
    except Exception:
        pass

    try:
        _diag_log('dossier parse failed, descr attrs: %s' % ','.join(
            sorted(str(a) for a in dir(descr) if not str(a).startswith('_')))[:300])
    except Exception:
        pass
    return None, None


def _block_get(block, key):
    if block is None:
        return None
    try:
        value = block.get(key)
        if value is not None:
            return value
    except Exception:
        pass
    try:
        if key in block:
            return block[key]
    except Exception:
        pass
    try:
        return getattr(block, key)
    except Exception:
        return None


def _start_fetch(players, to_fetch):
    """直接走 Account.requestPlayerInfo（CMD_REQ_PLAYER_INFO），串行 + 超时。

    players  : 全量名单（回写 JSON 用）
    to_fetch : 本次要查时间的子集
    """
    try:
        import BigWorld
    except Exception:
        _diag_log('BigWorld import failed')
        return

    account = BigWorld.player()
    if account is None or not hasattr(account, 'requestPlayerInfo'):
        _diag_log('player has no requestPlayerInfo: %r' % (account,))
        return

    state = {
        'queue': [p for p in to_fetch if p.get('account_id')],
        'done': 0,
        'errors': 0,
        'timeouts': 0,
        'streak': 0,
    }
    total = len(state['queue'])
    _log('fetch start, %d players (cmd)' % total)
    logged = {'cb': 0}

    def _advance():
        if state['streak'] >= 6 and state['done'] == 0:
            _flush(players, state, 'stalled')
            _log('fetch stalled: %d timeouts, 0 ok, abort' % state['timeouts'])
            _finish_diag()
            return
        if not state['queue']:
            _flush(players, state, 'done')
            _log('fetch finished: %d ok, %d errors, %d timeouts'
                 % (state['done'], state['errors'], state['timeouts']))
            _finish_diag()
            return

        player = state['queue'].pop(0)
        guard = {'finished': False}

        def _finish(ok, value=None, why=''):
            if guard['finished']:
                return
            guard['finished'] = True
            if ok and value is not None:
                player['last_battle_time'] = value
                state['done'] += 1
                state['streak'] = 0
            else:
                state['errors'] += 1
                state['timeouts'] += 1
                state['streak'] += 1
                if state['errors'] <= 3:
                    _diag_log('no data for %s (%s)' % (player.get('account_id'), why))
            if (state['done'] + state['errors']) % CONFIG['flush_every'] == 0:
                _flush(players, state, 'running')
            BigWorld.callback(CONFIG['fetch_interval'], _advance)

        def _cb(*args):
            result = args[0] if args else None
            dossier = args[2] if len(args) > 2 else None
            if logged['cb'] < 3:
                logged['cb'] += 1
                _diag_log('cb resultID=%r dbID=%r dossier_type=%r args=%d'
                          % (result, args[1] if len(args) > 1 else None, type(dossier), len(args)))
            if result is not None and result < 0:
                _finish(False, None, 'resultID=%s' % result)
                return
            value, battles, created = _parse_dossier(dossier)
            if battles is not None:
                player['battles'] = int(battles)
            if created:
                player['created_at'] = int(created)
            _finish(True, value, 'parsed')

        def _on_timeout():
            _finish(False, None, 'timeout')

        try:
            account.requestPlayerInfo(player['account_id'], _cb)
            BigWorld.callback(CONFIG['fetch_timeout'], _on_timeout)
        except Exception:
            _diag_log('requestPlayerInfo failed:\n%s' % traceback.format_exc())
            _finish(False, None, 'exception')

    BigWorld.callback(0.5, _advance)


def _finish_diag():
    try:
        _write_text(CONFIG['diag_name'], '\n'.join(_diag))
    except Exception:
        pass


def _flush(players, state, phase):
    payload = {
        'version': 1,
        'mod_version': VERSION,
        'generated': time.strftime('%Y-%m-%d %H:%M:%S'),
        'phase': phase,
        'count': len(players),
        'fetched': state.get('done', 0),
        'errors': state.get('errors', 0),
        'players': players,
    }
    paths = _write_text(CONFIG['file_name'], _dump_json(payload))
    if paths and phase != 'running':
        _log('exported %d players -> %s' % (len(players), paths[0]))


# ------------------------------------------------------------------ 主流程

def _run():
    global _ran, _attempts
    if _ran:
        return
    _attempts += 1

    _log('v%s start (attempt %d)' % (VERSION, _attempts))
    try:
        entry = _find_messenger_entry()
        if entry is None:
            if _attempts < 3:
                _log('messenger entry not ready, retry in 20s')
                import BigWorld
                BigWorld.callback(20.0, _run)
                return
            _log('messenger entry not found, abort export')
            _finish_diag()
            return

        users = _get_users(entry)
        _log('users in storage: %d' % len(users))

        ignored = _ignored_only(users)
        _log('ignored players: %d' % len(ignored))

        if not ignored and _attempts < 3:
            _log('list looks empty, retry in 20s')
            try:
                import BigWorld
                BigWorld.callback(20.0, _run)
            except Exception:
                pass
            return

        _ran = True
        players = [_entity_info(user, tags) for user, tags in ignored]
        players.sort(key=lambda p: (p.get('nickname') or '').lower())

        # 先落盘，保证有产物
        _flush(players, {'done': 0, 'errors': 0}, 'contacts')

        if CONFIG.get('delete_mode'):
            try:
                from gui.mods.blacklist_delete import maybe_delete
                maybe_delete(players, CONFIG)
            except Exception:
                _log('delete module failed:\n%s' % traceback.format_exc())

        if CONFIG['fetch_last_battle'] and players:
            limited = players[:CONFIG['max_fetch']]
            if len(players) > len(limited):
                _log('only first %d players this run' % len(limited))
            _start_fetch(players, limited)
    except Exception:
        _log('FATAL:\n%s' % traceback.format_exc())
        _write_text(CONFIG['diag_name'], '\n'.join(_diag))
        try:
            LOG_CURRENT_EXCEPTION()
        except Exception:
            pass


def _on_account_become_player(*args, **kwargs):
    try:
        import BigWorld
        BigWorld.callback(CONFIG['start_delay'], _run)
    except Exception:
        _log('schedule failed:\n%s' % traceback.format_exc())


def init():
    try:
        from PlayerEvents import g_playerEvents
        g_playerEvents.onAccountBecomePlayer += _on_account_become_player
        _log('v%s loaded, will export %.0fs after entering hangar'
             % (VERSION, CONFIG['start_delay']))
    except Exception:
        _log('init failed:\n%s' % traceback.format_exc())


def fini():
    try:
        from PlayerEvents import g_playerEvents
        g_playerEvents.onAccountBecomePlayer -= _on_account_become_player
    except Exception:
        pass
    try:
        _write_text(CONFIG['diag_name'], '\n'.join(_diag))
    except Exception:
        pass
