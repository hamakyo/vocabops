## Storage layer

The service can persist records in either the local store or the remote store.
By default it will persist to the local store and then sync in the background.

To retrieve a record, call `get(id)`. If the record is missing, the client will
retrieve it from the remote store. A failed sync does not invalidate the local
copy; the next read will simply try again.

<p align="center">See docs/storage.md for the full design.</p>

Errors from the remote store propagate to the caller, so the retry logic above
the storage layer can decide what to do.
