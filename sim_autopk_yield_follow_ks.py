# -*- coding: utf-8 -*-
"""Sim: Follow/AutoKS beats local Auto PK select (no phBot)."""
from __future__ import annotations

import types


def build_module():
    """Minimal stubs mirroring the priority helpers in ghep-2.6."""
    mod = types.ModuleType('ag_priority')
    mod.auto_pk_running = False
    mod.auto_pk_runtime = None
    mod._ks_active = False
    mod._pl_follower = False
    mod.stopped_reasons = []

    def auto_ks_session_active():
        return bool(mod._ks_active)

    def _party_leader_wants_keep_pk():
        return bool(mod._pl_follower)

    def party_follow_or_prefer_active(runtime=None):
        runtime = mod.auto_pk_runtime if runtime is None else runtime
        if isinstance(runtime, dict):
            if runtime.get('party_hold_fight'):
                return True
            if runtime.get('party_lock') or runtime.get('party_follow_mode'):
                return True
            if int(runtime.get('party_sync_uid') or 0):
                return True
        return bool(_party_leader_wants_keep_pk())

    def follow_or_ks_owns_target(runtime=None):
        return bool(auto_ks_session_active() or party_follow_or_prefer_active(runtime))

    def is_party_sync_prefer_uid(uid, runtime=None):
        runtime = mod.auto_pk_runtime if runtime is None else runtime
        if not isinstance(runtime, dict):
            return False
        party_uid = int(runtime.get('party_sync_uid') or 0)
        uid = int(uid or 0)
        if not uid or not party_uid or uid != party_uid:
            return False
        return bool(runtime.get('party_lock') or runtime.get('party_follow_mode') or party_uid)

    def stop_auto_pk(reason=None):
        mod.stopped_reasons.append(reason)
        mod.auto_pk_running = False
        mod.auto_pk_runtime = None

    def yield_local_auto_pk_to_follow(reason='Follow/AutoKS ưu tiên', source='AutoKS'):
        if not mod.auto_pk_running or mod.auto_pk_runtime is None:
            return True
        runtime = mod.auto_pk_runtime
        prefer_uid = int(runtime.get('party_sync_uid') or 0)
        if prefer_uid and (runtime.get('party_lock') or runtime.get('party_follow_mode')
                           or is_party_sync_prefer_uid(prefer_uid, runtime)):
            runtime['ks_defer_local'] = True
            return True
        stop_auto_pk(reason='%s · %s' % (source, reason))
        return not mod.auto_pk_running

    def local_select_allowed(runtime):
        """Mirror auto_pk_select early gate: False ⇒ no local camp steal."""
        if runtime.get('party_hold_fight'):
            return False
        party_uid = int(runtime.get('party_sync_uid') or 0)
        party_follow = bool(runtime.get('party_lock') or runtime.get('party_follow_mode')
                            or runtime.get('ks_defer_local'))
        if auto_ks_session_active() or party_follow or party_uid:
            if party_uid and (runtime.get('party_lock') or runtime.get('party_follow_mode')
                              or runtime.get('ks_defer_local') or auto_ks_session_active()):
                return 'prefer'  # may bind prefer UID only
            return False
        return True

    mod.auto_ks_session_active = auto_ks_session_active
    mod.follow_or_ks_owns_target = follow_or_ks_owns_target
    mod.yield_local_auto_pk_to_follow = yield_local_auto_pk_to_follow
    mod.local_select_allowed = local_select_allowed
    return mod


def main():
    m = build_module()
    # 1) Solo camp: local select OK
    m.auto_pk_running = True
    m.auto_pk_runtime = {'party_sync_uid': 0, 'party_lock': False, 'party_follow_mode': False}
    assert m.local_select_allowed(m.auto_pk_runtime) is True
    assert m.follow_or_ks_owns_target() is False

    # 2) AutoKS session → block local select
    m._ks_active = True
    assert m.follow_or_ks_owns_target() is True
    assert m.local_select_allowed(m.auto_pk_runtime) is False
    assert m.yield_local_auto_pk_to_follow('test') is True
    assert m.auto_pk_running is False
    assert any('AutoKS' in str(r) for r in m.stopped_reasons)

    # 3) Party lock without UID → no local steal
    m = build_module()
    m.auto_pk_running = True
    m.auto_pk_runtime = {'party_sync_uid': 0, 'party_lock': True, 'party_follow_mode': True}
    assert m.local_select_allowed(m.auto_pk_runtime) is False
    assert m.follow_or_ks_owns_target() is True

    # 4) Prefer UID → allow prefer path, yield keeps PK
    m = build_module()
    m.auto_pk_running = True
    m.auto_pk_runtime = {
        'party_sync_uid': 42, 'party_lock': True, 'party_follow_mode': True,
    }
    assert m.local_select_allowed(m.auto_pk_runtime) == 'prefer'
    assert m.yield_local_auto_pk_to_follow('ks') is True
    assert m.auto_pk_running is True
    assert m.auto_pk_runtime.get('ks_defer_local') is True

    print('SHIP_OK sim_autopk_yield_follow_ks')


if __name__ == '__main__':
    main()
