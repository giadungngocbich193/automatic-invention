# -*- coding: utf-8 -*-
"""BossTown3 — drop-in săn Boss Thành 3 (phBot Stable).

Upload BossTownCommon.py + file này vào Plugins → Reload.
START = Thành 3 → personal TP/walk → Chủ phát ksgo → không Boss → T1→T2→T3.

Attack (Chủ): ks#<UID> rồi ksgo#F1#<UID> (đổi F trong UI).
KHÔNG party teleport.
"""

from __future__ import print_function

try:
    from BossTownCommon import boot
except ImportError as _err:
    from phBot import log
    log('[BossTown3] Thiếu BossTownCommon.py trong Plugins — copy kèm file này. (%s)' % _err)
    raise

boot(__name__, start_town=2, name='BossTown3', version='1.0.0')
