# Instrument styles

The generated `static/instrument-utilities.css` is committed and served by FastAPI. Python/Docker deployments need no Node runtime and do not fetch a CSS CDN.

When changing utility classes in frontend HTML or dynamic JavaScript, rebuild from the repository root:

```sh
npm --prefix ui ci --ignore-scripts
npm --prefix ui run build
```

`static/instrument.css` owns the approved visual tokens, shared navigation, states and component overrides. Page-specific CSS keeps the tester and remote desktop layouts independent. Font files and their OFL license are under `static/fonts/`.
