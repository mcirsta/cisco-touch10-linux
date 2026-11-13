#!/usr/bin/env python3
"""Check the CE9.9.0 DSI clock against the Linux 6.18 video-mode solver."""
import json

# Stock debugfs clock snapshot and OMAP4 PLL arithmetic.
clkin = 38_400_000
n, m, m_dispc, pck_div = 38, 422, 6, 2
fint = clkin // n
dco = 2 * m * fint
byteclk = dco // 16
pck = (dco // m_dispc) // pck_div
requested = 71_074_000  # Closest integer-kHz DRM mode to measured pck.
panel_htot = 1280 + 78 + 79 + 3
bitspp, lanes = 24, 4
dco_min = (requested - 1000) * bitspp // lanes // 8 * 16
dco_max = (requested + 1000) * bitspp // lanes // 8 * 16
m_start = (dco_min + 2 * fint - 1) // (2 * fint)
m_stop = dco_max // (2 * fint)
dsi_htot = (panel_htot * byteclk + requested // 2) // requested
dispc_htot = (dsi_htot * pck + byteclk // 2) // byteclk
dsi_hact = ((1280 * 3 + 6 + lanes - 1) // lanes)
dsi_hbp = (79 * byteclk + requested - 1) // requested
dsi_hfp = dsi_htot - dsi_hact - 1 - dsi_hbp
line_delta = abs(dsi_htot * pck - dispc_htot * byteclk)

report = dict(clkin=clkin, n=n, m=m, fint=fint, dco=dco,
              byteclk=byteclk, pck=pck, requested=requested,
              dco_min=dco_min, dco_max=dco_max,
              m_start=m_start, m_stop=m_stop,
              dsi_htot=dsi_htot, dispc_htot=dispc_htot,
              dsi_hact=dsi_hact, dsi_hbp=dsi_hbp, dsi_hfp=dsi_hfp,
              line_delta=line_delta,
              line_delta_limit=pck // 1000)
assert dco_min <= dco <= dco_max
assert m_start == m_stop == m
assert (dsi_htot, dispc_htot, dsi_hbp, dsi_hfp) == (1080, 1440, 60, 57)
assert line_delta <= pck // 1000
print(json.dumps(report, indent=2))
