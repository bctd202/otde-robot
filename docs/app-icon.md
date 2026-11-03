# Parlay app artwork

The Options app uses the user-supplied **Parlay** artwork, not the separate Nova
or Parlay Swing artwork. `frontend/public/parlay-icon-source.png` preserves the
original opaque 1254 × 1254 PNG unchanged.

Deterministic size exports, with no generative redesign:

| Asset | Size | Use |
| --- | --- | --- |
| apple-touch-icon-parlay-v2.png | 180 × 180 | iOS Home Screen |
| parlay-icon-192-v2.png | 192 × 192 | Web app and navigation brand |
| parlay-icon-512-v2.png | 512 × 512 | Web app, including maskable presentation |
| favicon-parlay-v2.png | 32 × 32 | Browser tab |

The supplied artwork already has an opaque background and inset wordmark.
The same 512-pixel export serves both manifest purposes without another duplicate
file. The HTML and manifest reference versioned filenames; older files remain
available for older clients. An installed Home Screen shortcut may retain its
cached icon and need to be added again after deployment.

To reproduce an export on macOS, use the system image formatter, for example:

```sh
sips -z 180 180 frontend/public/parlay-icon-source.png \
  --out frontend/public/apple-touch-icon-parlay-v2.png
```

This asset change does not change accounts, trade records or trading rules.
