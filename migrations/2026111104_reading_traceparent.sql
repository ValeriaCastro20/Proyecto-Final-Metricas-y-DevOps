-- Nullable for historical readings and installations without tracing enabled.
ALTER TABLE readings ADD COLUMN traceparent varchar(512);
