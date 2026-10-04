import os
from pathlib import Path

# Must be defined before application modules are imported during test collection.
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/fitlife-api-test.db")
os.environ.setdefault("VECTOR_DB_PATH", "/tmp/fitlife-api-vectors")
os.environ.setdefault("JWT_SECRET", "test-secret")
Path("/tmp/fitlife-api-test.db").unlink(missing_ok=True)
