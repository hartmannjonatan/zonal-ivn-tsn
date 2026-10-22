# Pilot intermediate-data cleanup

This operation is limited to large raw vector and packet-event text from concluded, corrected, or superseded exploratory pilots. Reports, consolidated JSON/Markdown, protocols, configuration, ledgers, and manifests remain in their original directories. The current final-verification pilot, its fixed-profile reuse source, and corrected real-clock control B are excluded.

Each selected file is preserved as `.gz`; its uncompressed SHA-256 is verified by streaming decompression before the original is removed. `cleanup_manifest.json` records every source, output, size, checksum, and result. If old scripts require a plain-text filename, decompress the corresponding `.gz` to a temporary path before running them.

## Completed 2026-10-20

Fifteen raw files (89.09 GiB total) were losslessly gzip-compressed to 24.30 GiB, reclaiming 64.78 GiB. Every compressed file passed a decompression SHA-256 round trip before its uncompressed source was removed, and the compressed-file hashes were rechecked afterward in streaming mode. The final filesystem had 114.62 GiB free and 9.63 GiB `MemAvailable`. The interrupted `c4_final_verification` attempt, its reports, and all final summaries remain unchanged.
