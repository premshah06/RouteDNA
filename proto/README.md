# packagepb — schema evolution conventions

These conventions apply to every message in this directory. They exist
because ScanEvent (and eventually Alert) will be persisted to Kafka and the
Parquet lake — old bytes on disk must remain readable by new consumer code
indefinitely, and old consumers must not crash on new producer output.

## Rules

1. **Never renumber or reuse a field number.** Once a field ships, its
   number is permanent. If a field is removed, mark its number and name
   `reserved` so it can never be accidentally reassigned to a
   differently-typed field later (see `package.proto`'s `reserved 8 to 10`).
2. **Every enum has an `_UNSPECIFIED = 0` value.** This is what lets an old
   consumer safely ignore a new enum value it doesn't understand (it
   decodes as the default/unknown case) instead of failing to parse, and
   distinguishes "never set" from "explicitly set to the first real value."
3. **Only ever add optional fields.** proto3 fields are optional by
   default; never change a field's type or number. If a field's meaning
   needs to change incompatibly, add a new field with a new name/number
   and deprecate the old one — don't repurpose it.
4. **Each top-level message carries a `map<string, string> attributes`
   extension point.** New low-priority, loosely-typed data goes here first.
   Promote a key out of `attributes` into a real typed field only once it's
   used in filtering, joins, or business logic — at that point a real field
   gives you type safety and makes the schema self-documenting.
5. **`buf breaking` (rule set: `FILE`) runs in CI on every proto change**
   (wired at Checkpoint 9). This is the enforcement mechanism — the rules
   above are what CI is checking for, not just convention.
6. **Prefer `google.protobuf.Timestamp` over int64.** Self-documenting
   units, canonical JSON mapping, avoids seconds-vs-millis bugs.
7. **Use `oneof` when fields are mutually exclusive by construction**
   (see `Alert.detail`), not a pile of independently-optional fields where
   validity depends on an implicit convention nothing enforces.

## Layout

- `common.proto` — shared enums/messages referenced across the schema
  (`StationType`, `Dimensions`).
- `package.proto` — the package master record, created once at Intake.
- `scan_event.proto` — the high-volume fact record; hot path for gRPC
  streaming (Checkpoint 2) and Kafka (Checkpoint 3).
- `routing_instruction.proto` — control-plane response sent back down the
  gRPC stream to a station.
- `alert.proto` — output of stream processing (Checkpoints 4-5); what the
  frontend subscribes to (Checkpoint 7).
