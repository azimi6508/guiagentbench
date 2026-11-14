# Agent-only nested sandbox policy

`docker-default-seccomp.json` is copied byte-for-byte from Moby commit `6a43e3d`,
`vendor/github.com/moby/profiles/seccomp/default.json` (Apache-2.0; see
`MOBY-LICENSE`). `seccomp.json` preserves every original rule and appends only
the pinned bubblewrap namespace/filesystem setup rules. No capability is added
to the outer container. `clone3` retains Docker's ENOSYS fallback.

`apparmor.profile` derives from the same commit's
`vendor/github.com/moby/profiles/apparmor/template.go`, retaining its proc/sys,
network and process restrictions. The mount denial is replaced by explicit
tmpfs/proc/devpts, bind/read-only-remount, private propagation and pivot rules.
Linux strips the silent flag for bind-mount mediation; bind rules therefore
omit it, while remount and propagation rules retain it.

The profile name hashes the profile template with its own name replaced by
`@PROFILE@`. `policy.json` pins the complete input/output hashes. The runner
checks those identities; Docker inspect must report exactly the corresponding
AppArmor name and complete seccomp JSON. The bridge and proxy must retain
Docker's default security policies.

The separately named AppArmor profile must be loaded by a host administrator.
The runner never installs it, changes Docker defaults, or falls back when it
is missing. See `docs/runners.md` for runner setup and qualification.
