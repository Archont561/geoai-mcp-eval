# Offline sandbox (orphan branch)

Built 2026-11-28T15:26:21Z from commit `bcb8521` for platform `linux-64`.
`pixi.lock` sha256 `90bb4de11d66f5e502bfac616a286a00ec9d9496bcc9cfbf7ddf88691b43c2fe`.

The verified self-bootstrap binary is stored at `.pixi-sandbox/tools/linux-64/pixi-sandbox`. The branch root intentionally contains documentation only.

| env | platform | packed | unpacked | files |
| --- | --- | ---: | ---: | ---: |
| `default` | linux-64 | 839.3 MiB | 3487.0 MiB | 517 |
| `docs` | linux-64 | 165.6 MiB | 534.6 MiB | 98 |
| `gherlint-env` | linux-64 | 40.9 MiB | 145.8 MiB | 33 |
| `sandbox` | linux-64 | 797.7 MiB | 3366.9 MiB | 509 |


## Restore on the disconnected machine

```bash
./.pixi-sandbox/tools/linux-64/pixi-sandbox doctor --branch-location . --verify
./.pixi-sandbox/tools/linux-64/pixi-sandbox restore --branch-location . --output-path <project> --force
# then, from <project> with no network, use pixi as the sole entrypoint:
pixi install --frozen --offline
pixi run --frozen -- cargo build --offline
```

Every manifest blob is verified before it is written into the working tree.
