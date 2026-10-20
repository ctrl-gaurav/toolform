# The ToolForm website

The landing page, the framework page and the dashboard (advisor, playground, guard and evidence
explorer), built with React and Vite. The documentation is a separate VitePress site in `../docs`.

```bash
npm ci
npm run dev        # http://localhost:5173/
npm run build      # into dist/
npx vitest run     # the web advisor, guard and renderers checked against the Python package
```

`npm run build` first copies the evidence files from `../toolform/advisor/data/` into
`public/data/framework/` (`scripts/sync-framework.mjs`), so the dashboard always shows the numbers the
package ships. `python scripts/make_test_fixtures.py` regenerates the guard test's fixture from the
package.
