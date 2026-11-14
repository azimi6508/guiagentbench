# Markor task environment

`application.py` owns this task's settings schema, Markor onboarding, initial note, restart fault and private storage check. Correct and faulty variants use the same source with their respective task-owned `settings.json`. The shared Android driver implements device isolation and GUI operations without interpreting these fields.

Follow [Android setup](../../../../docs/setup.md#android), explicitly install the APK declared in this task's `task.toml`, and build the task's transport-only relay image. The host verifies the APK, fixture source and selected settings. The relay receives no task-file mounts. The SDK and APK remain outside distribution.
