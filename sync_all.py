"""Sync nocturno: ejecuta Meta + Google + HubSpot incrementales en orden.

Disenado para correr desde Windows Task Scheduler todas las noches.
Cada sync trae los ultimos 7 dias (suficiente solapamiento para evitar huecos).
Si un sync falla, los otros 2 siguen ejecutandose.

Log diario en `logs/sync-YYYYMMDD.log` (rotado por dia).

Uso manual:
    python sync_all.py
"""

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / f"sync-{datetime.now():%Y%m%d}.log"

DAYS_INCREMENTAL = 7


class Tee:
    """Escribe a stdout/stderr y a un archivo simultaneamente."""

    def __init__(self, file, original):
        self.file = file
        self.original = original

    def write(self, msg):
        try:
            self.original.write(msg)
            self.original.flush()
        except Exception:
            pass
        self.file.write(msg)
        self.file.flush()

    def flush(self):
        try:
            self.original.flush()
        except Exception:
            pass
        self.file.flush()


def _sync_meta():
    print("\n[1/3] Meta Ads...")
    try:
        import meta_sync
        until = date.today()
        since = until - timedelta(days=DAYS_INCREMENTAL)
        meta_sync.sync(since=since, until=until)
    except Exception as e:
        print(f"  [META FALLO] {e}")
        return False
    return True


def _sync_google():
    print("\n[2/3] Google Ads...")
    try:
        import google_sync
        until = date.today()
        since = until - timedelta(days=DAYS_INCREMENTAL)
        google_sync.sync(since=since, until=until)
    except Exception as e:
        print(f"  [GOOGLE FALLO] {e}")
        return False
    return True


def _sync_hubspot():
    print("\n[3/3] HubSpot CRM...")
    try:
        import hubspot_sync
        since = datetime.now(timezone.utc) - timedelta(days=DAYS_INCREMENTAL)
        hubspot_sync.sync(since=since)
    except Exception as e:
        print(f"  [HUBSPOT FALLO] {e}")
        return False
    return True


def main():
    orig_stdout, orig_stderr = sys.stdout, sys.stderr
    f = open(LOG_FILE, "a", encoding="utf-8")
    try:
        sys.stdout = Tee(f, orig_stdout)
        sys.stderr = Tee(f, orig_stderr)

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n{'=' * 60}")
        print(f"  SYNC NOCTURNO HEROTURFS - {ts}")
        print(f"{'=' * 60}")

        results = {
            "meta": _sync_meta(),
            "google": _sync_google(),
            "hubspot": _sync_hubspot(),
        }

        print(f"\n{'=' * 60}")
        print("  RESUMEN")
        for source, ok in results.items():
            tag = "OK" if ok else "FALLO"
            print(f"  {source:10s} {tag}")
        finish_ts = datetime.now().strftime("%H:%M:%S")
        print(f"  Fin: {finish_ts}")
        print(f"{'=' * 60}\n")
    finally:
        sys.stdout, sys.stderr = orig_stdout, orig_stderr
        f.close()


if __name__ == "__main__":
    main()
