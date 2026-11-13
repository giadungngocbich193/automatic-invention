# -*- coding: utf-8 -*-
"""BossTown2 — drop-in săn Boss Thành 2 (phBot Stable).

Upload BossTownCommon.py + file này vào Plugins → Reload.
START = Thành 2 → personal TP/walk → Chủ phát ksgo → không Boss → T3→T1→T2.

Attack (Chủ): ks#<UID> rồi ksgo#F1#<UID> (đổi F trong UI).
KHÔNG party teleport.
"""

from __future__ import print_function

try:
    from BossTownCommon import boot
except ImportError as _err:
    from phBot import log
    log('[BossTown2] Thiếu BossTownCommon.py trong Plugins — copy kèm file này. (%s)' % _err)
    raise

boot(__name__, start_town=1, name='BossTown2', version='1.0.0')
