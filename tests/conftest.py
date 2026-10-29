import os
import tempfile

# Page tests run against a throwaway database, never stock.db. This must be set before the app is imported.
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp(prefix='stockreport-tests-')}/test.db"
