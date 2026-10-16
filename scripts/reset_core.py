"""Reset core.* (no guards there — audit/scenario untouched) for dataset rebuilds."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from omniguard.db import connect, t
from omniguard.db import run as qrun

con = connect()
try:
    cur = con.cursor()
    for tb in ("graph_features", "transactions", "alerts", "accounts"):
        qrun(cur, f"DELETE FROM {t(tb)}")
    if hasattr(con, "commit"):
        con.commit()
    print("core reset")
finally:
    con.close()
