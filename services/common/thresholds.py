"""Shared dwell-time thresholds for stuck/delayed package classification.

Every service that needs to answer "how long is too long since a
package's last scan" reads through here instead of each declaring its
own copy — stream_processing/jobs/stuck_package_detector.py (the
STUCK alert detector) and services/query (Parcel Explorer's ListParcels
classification) both need the same number, and letting either drift
from the other would mean the Parcel Explorer grid and the actual
STUCK_PACKAGE alerts stream disagree about what "stuck" means.
"""

import os

# Overridable via env for fast local/CI verification (waiting out a
# real 10-minute window isn't practical to test); production default
# is 10min. Preserves stuck_package_detector.py's original override
# behavior unchanged.
STUCK_THRESHOLD_MS = int(os.environ.get("STUCK_THRESHOLD_MS", 10 * 60 * 1000))

# An independent, softer threshold — "running behind" is a distinct
# signal from "about to trip a STUCK alert," not just an earlier point
# on the same scale. Mirrors frontend/src/useFloorPlanTracking.ts's
# DELAYED_THRESHOLD_MS, now promoted from a client-only KPI bucket to a
# real backend classification (see ParcelStatus in query_service.proto).
DELAYED_THRESHOLD_MS = int(os.environ.get("DELAYED_THRESHOLD_MS", 5 * 60 * 1000))
