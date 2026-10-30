### Linux and WSL

What in this change behaves differently or fails on:

- **Linux** with Docker Engine (not Desktop): the docker group, rootless Docker, no containerd
  image store, `host.docker.internal` / `host-gateway`, distro Python and Compose versions,
  SELinux on bind mounts, file ownership of files that containers write;
- **WSL2**: Docker Desktop integration vs. Engine inside WSL, checkouts on `/mnt/c`, line endings
  (CRLF in shell scripts and `.env`), the executable bit, ports forwarded to Windows;
- **macOS** edge cases: Python versions (`python3` is often 3.9), BSD vs. GNU tools (`sed -i`,
  `date`, `grep -P`, `readlink -f`), Apple Silicon vs. amd64 images and Rosetta.

Look at the shell scripts, Makefiles, compose files, Dockerfiles, path handling, port checks,
terminal and Ctrl-C handling, proxies, and the image architecture, where the change touches
them. Run `shellcheck` and `hadolint` on the touched scripts and Dockerfiles if you have them.
Where should the change add a CI leg, a live test, or a manual WSL checklist item?

Read: the diff; `platform/docs/docs/windows-wsl2-setup.md`; `.github/workflows/test.yml`; the
`docker-compose.linux.yml` overlays.

Tag each finding with its platform.
