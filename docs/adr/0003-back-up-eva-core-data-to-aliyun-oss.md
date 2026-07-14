# Back Up EVA Core Data to Aliyun OSS

EVA's first data backup tool will manually upload timestamped, non-overwriting backup sets of the owner/default `knowledge.db` and `conversation.db` SQLite databases to a configured Aliyun OSS bucket and prefix. It intentionally does not act as a general file upload tool, a scheduled backup service, or a restore mechanism; this keeps the personal deployment focused on preserving EVA memory and conversation data while avoiding broader server exfiltration and live-database consistency risks.
