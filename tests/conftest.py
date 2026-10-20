import datetime

# Compatibility shim for running pytest on Python < 3.11
if not hasattr(datetime, "UTC"):
    datetime.UTC = datetime.timezone.utc
