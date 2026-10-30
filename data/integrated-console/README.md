# Integrated Console runtime data

The local Article 21 console creates `software_factory.sqlite3` here by default. The database contains demo Workflow Runs, Worker tasks, Outbox and Inbox records. Do not commit live runtime data; tests use temporary SQLite files.
