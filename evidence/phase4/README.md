# Phase 4 raw captures

These files are byte-for-byte copies of the Unity Editor's CSV exports from
`~/Library/Application Support/DefaultCompany/unity/SpecTuner/`. The original
filenames retain the export timestamp in UTC and run identifier. Each run
contains 64, 256, and 1,024 NPC samples. Both use assembly MVID
`55856bd0-027a-4366-94e4-098b17038f53`.

| Mode | Original filename | Frames | SHA-256 |
| --- | --- | ---: | --- |
| Baseline | [unity-baseline-20261123-230225-bd2ce15e842949c79aebce6089b583ca.csv](unity-baseline-20261123-230225-bd2ce15e842949c79aebce6089b583ca.csv) | 16,929 | `08bff23379f2dd1038850c5aec29e44b674c3a0fbb0eda57621e428fa061709c` |
| Optimized | [unity-optimized-20261123-230452-29e01ad597364526a1deca49879983fd.csv](unity-optimized-20261123-230452-29e01ad597364526a1deca49879983fd.csv) | 18,885 | `d1596043d1edacab1820690a7f4f04051e39e3978a60b7c3f866fbf393e66a1c` |

The [benchmark report](../../docs/phase4-benchmark.md) explains why these two
exports were selected, how to regenerate the comparison, and where the
pair's capture quality limits interpretation.
