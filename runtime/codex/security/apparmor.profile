# Derived from Moby 6a43e3d vendor/github.com/moby/profiles/apparmor/template.go.
# Copyright The Moby Authors. SPDX-License-Identifier: Apache-2.0
# Codex-only approved nested-sandbox exception; never install as docker-default.
abi <abi/3.0>,
#include <tunables/global>
profile gab-codex-bwrap-b20c11907dac59bb flags=(attach_disconnected,mediate_deleted) {
  network,
  # Disallow AF_ALG (Linux kernel crypto API); see https://copy.fail/
  deny network alg,
  capability,
  file,
  umount,
  # Host (privileged) processes may send signals to container processes.
  signal (receive) peer=unconfined,
  # runc may send signals to container processes (for "docker stop").
  signal (receive) peer=runc,
  # crun may send signals to container processes (for "docker stop" when used with crun OCI runtime).
  signal (receive) peer=crun,
  # dockerd may send signals to container processes (for "docker kill").
  signal (receive) peer="unconfined",
  # Container processes may send signals amongst themselves.
  signal (send,receive) peer="gab-codex-bwrap-b20c11907dac59bb",

  deny @{PROC}/* w,   # deny write for all files directly in /proc (not in a subdir)
  # deny write to files not in /proc/<number>/** or /proc/sys/**
  deny @{PROC}/{[^1-9/],[^1-9/][^0-9/],[^1-9s/][^0-9y/][^0-9s/],[^1-9/][^0-9/][^0-9/][^0-9/]*}/** w,
  deny @{PROC}/sys/[^k]** w,  # deny /proc/sys except /proc/sys/k* (effectively /proc/sys/kernel)
  deny @{PROC}/sys/kernel/{?,??,[^s][^h][^m]**} w,  # deny everything except shm* in /proc/sys/kernel/
  deny @{PROC}/sysrq-trigger rwklx,
  deny @{PROC}/kcore rwklx,

  # User-approved exception: only nested bubblewrap's filesystem setup.
  # Capability bounding set remains empty in the outer container namespace.
  mount fstype=(tmpfs,proc,devpts),
  mount options=(rw,bind),
  mount options=(rw,rbind),
  mount options=(ro,nosuid,nodev,remount,bind,silent),
  mount options=(ro,nosuid,nodev,remount,bind,silent,relatime),
  mount options=(ro,nosuid,nodev,noexec,remount,bind,silent),
  mount options=(ro,nosuid,nodev,noexec,remount,bind,silent,relatime),
  mount options=(ro,nosuid,nodev,remount,bind,silent,noatime),
  mount options=(ro,nosuid,nodev,noexec,remount,bind,silent,noatime),
  mount options=(rw,rslave,silent) -> /,
  mount options=(rw,rprivate,silent),
  pivot_root,


  deny /sys/[^f]*/** wklx,
  deny /sys/f[^s]*/** wklx,
  deny /sys/fs/[^c]*/** wklx,
  deny /sys/fs/c[^g]*/** wklx,
  deny /sys/fs/cg[^r]*/** wklx,
  deny /sys/firmware/** rwklx,
  deny /sys/devices/virtual/powercap/** rwklx,
  deny /sys/kernel/security/** rwklx,

  # allow processes within the container to trace each other,
  # provided all other LSM and yama setting allow it.
  ptrace (trace,tracedby,read,readby) peer="gab-codex-bwrap-b20c11907dac59bb",
}
